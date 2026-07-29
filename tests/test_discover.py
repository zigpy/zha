"""Test ZHA device discovery."""

import asyncio
from collections import defaultdict
from collections.abc import Callable
import contextlib
import dataclasses
import enum
import json
import pathlib
import re
from unittest import mock
from unittest.mock import AsyncMock
import warnings

import attrs
import pytest
from zhaquirks.builder import QuirkBuilder
from zhaquirks.builder.metadata import (
    BinarySensorMetadata,
    NumberMetadata,
    ZCLSensorMetadata,
)
from zhaquirks.ikea import PowerConfig1CRCluster, ScenesCluster
from zhaquirks.xiaomi import (
    BasicCluster,
    LocalIlluminanceMeasurementCluster,
    XiaomiPowerConfigurationPercent,
)
from zhaquirks.xiaomi.aqara.driver_curtain_e1 import (
    WindowCoveringE1,
    XiaomiAqaraDriverE1,
)
import zigpy.device
import zigpy.profiles.zha
import zigpy.types
from zigpy.zcl import ClusterType
import zigpy.zcl.clusters.closures
import zigpy.zcl.clusters.general
from zigpy.zcl.clusters.general import Ota, QueryNextImageCommand
import zigpy.zcl.clusters.security
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    ZhaJsonEncoder,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    update_attribute_cache,
    zigpy_device_from_device_data,
    zigpy_device_from_json,
)
from zha.application import EntityType, Platform
from zha.application.gateway import Gateway
from zha.application.helpers import DeviceOverridesConfiguration
from zha.application.platforms import PlatformEntity, binary_sensor, sensor
from zha.application.platforms.const import PHILIPS_REMOTE_CLUSTER
from zha.application.platforms.light import HueLight
from zha.application.platforms.number import BaseNumber, NumberMode
from zha.quirks import QUIRK_REGISTRY_ENTRY_ATTR, DeviceMatch, DeviceRegistry, ModelInfo
from zha.units import UnitOfTime


def _get_identify_cluster(zigpy_device):
    for endpoint in list(zigpy_device.endpoints.values())[1:]:
        if hasattr(endpoint, "identify"):
            return endpoint.identify


@pytest.mark.parametrize("override_platform", [Platform.SWITCH, Platform.LIGHT])
async def test_device_override(
    zha_gateway: Gateway, override_platform: Platform
) -> None:
    """Test device discovery override."""

    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-basiczbr3.json",
    )

    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-1": DeviceOverridesConfiguration(type=override_platform)
    }

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    # The overridden entity exists at the endpoint-level unique_id
    entity = zha_device.get_platform_entity(
        override_platform, unique_id=f"{zigpy_device.ieee}-1"
    )
    assert entity is not None

    # The non-overridden platform has no such entity
    other_platform = (
        Platform.LIGHT if override_platform == Platform.SWITCH else Platform.SWITCH
    )
    with pytest.raises(KeyError):
        zha_device.get_platform_entity(
            other_platform, unique_id=f"{zigpy_device.ieee}-1"
        )


async def test_device_override_entities(zha_gateway: Gateway) -> None:
    """Test device discovery entity changes."""
    device_data_text = await asyncio.get_running_loop().run_in_executor(
        None,
        pathlib.Path(
            "tests/data/devices/tz3000-tqlv4ug4-ts0001-0x00000048.json"
        ).read_text,
    )
    device_data = json.loads(device_data_text)

    zigpy_device = zigpy_device_from_device_data(
        app=zha_gateway.application_controller, device_data=device_data
    )

    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-1": DeviceOverridesConfiguration(type=Platform.SWITCH)
    }

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    # The light is gone
    with pytest.raises(KeyError):
        get_entity(zha_device, platform=Platform.LIGHT)

    # And has been replaced by a switch with the same unique ID
    switch = get_entity(zha_device, platform=Platform.SWITCH)
    assert switch.unique_id == f"{zigpy_device.ieee}-1"

    # All other entities and diagnostics stay the same
    loaded_device_data = json.loads(
        json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
    )

    expected_loaded_device_data = device_data
    expected_loaded_device_data["zha_lib_entities"].pop("light")
    expected_loaded_device_data["zha_lib_entities"]["switch"] = [
        loaded_device_data["zha_lib_entities"]["switch"][0]
    ]

    assert loaded_device_data == expected_loaded_device_data


async def test_device_override_picks_highest_priority(
    zha_gateway: Gateway,
) -> None:
    """Test that a device override selects only the highest-priority match."""

    # A Philips light matches both Light (priority 0) and HueLight (priority 1) in the
    # LIGHT_OR_SWITCH_OR_SHADE feature group. With a SWITCH override, only one Switch
    # entity should be created, not duplicates from collecting all priority levels.
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/philips-lct014-0x01001a02.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    # Only one light entity will be discovered
    entities = list(zha_device.discover_entities())
    light_entities = [e for e in entities if e.PLATFORM == Platform.LIGHT]
    assert len(light_entities) == 1
    assert isinstance(light_entities[0], HueLight)

    # With an override, it is going to be one switch
    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-11": DeviceOverridesConfiguration(type=Platform.SWITCH)
    }

    entities = list(zha_device.discover_entities())
    switch_entities = [e for e in entities if e.PLATFORM == Platform.SWITCH]
    assert len(switch_entities) == 1


async def test_device_override_filter_bypassing(
    zha_gateway: Gateway,
) -> None:
    """Test that profile filtering is only bypassed for the override platform."""

    # The sercomm device is an ON_OFF_LIGHT with a PowerConfiguration cluster.
    # DeviceTracker matches PowerConfiguration but is restricted by profile_device_types
    # to the SmartThings arrival sensor device type. A SWITCH override should not cause
    # DeviceTracker to bypass that filter.
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sercomm-corp-sz-esw01-au.json",
    )

    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-1": DeviceOverridesConfiguration(type=Platform.SWITCH)
    }

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    with pytest.raises(KeyError):
        get_entity(zha_device, platform=Platform.DEVICE_TRACKER)


async def test_quirks_v2_entity_discovery(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test quirks v2 discovery."""

    registry = DeviceRegistry()
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    zigpy.zcl.clusters.general.PowerConfiguration.cluster_id,
                    zigpy.zcl.clusters.general.Groups.cluster_id,
                    zigpy.zcl.clusters.general.OnOff.cluster_id,
                ],
                SIG_EP_OUTPUT: [
                    zigpy.zcl.clusters.general.Scenes.cluster_id,
                ],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.NON_COLOR_CONTROLLER,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee="01:2d:6f:00:0a:90:69:e8",
        manufacturer="Ikea of Sweden",
        model="TRADFRI remote control",
        registry=registry,
    )

    (
        QuirkBuilder("Ikea of Sweden", "TRADFRI remote control")
        .replaces(PowerConfig1CRCluster)
        .replaces(ScenesCluster, cluster_type=ClusterType.Client)
        .number(
            zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            zigpy.zcl.clusters.general.OnOff.cluster_id,
            min_value=1,
            max_value=100,
            step=1,
            unit=UnitOfTime.SECONDS,
            multiplier=1,
            mode="box",
            translation_key="off_wait_time",
            fallback_name="Off wait time",
        )
        .add_to_registry(registry)
    )

    zigpy_device = registry.resolve(zigpy_device)
    zigpy_device.endpoints[1].power.PLUGGED_ATTR_READS = {
        "battery_voltage": 3,
        "battery_percentage_remaining": 100,
    }
    update_attribute_cache(zigpy_device.endpoints[1].power)
    zigpy_device.endpoints[1].on_off.PLUGGED_ATTR_READS = {
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name: 3,
    }
    update_attribute_cache(zigpy_device.endpoints[1].on_off)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    number_entity = get_entity(zha_device, platform=Platform.NUMBER)
    assert isinstance(number_entity, BaseNumber)
    assert number_entity.mode == NumberMode.BOX  # verify v2 quirk set this


async def test_quirks_v2_entity_discovery_e1_curtain(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test quirks v2 discovery for e1 curtain motor."""

    class AqaraE1HookState(zigpy.types.enum8):
        """Aqara hook state."""

        Unlocked = 0x00
        Locked = 0x01
        Locking = 0x02
        Unlocking = 0x03

    class FakeXiaomiAqaraDriverE1(XiaomiAqaraDriverE1):
        """Fake XiaomiAqaraDriverE1 cluster."""

        attributes = XiaomiAqaraDriverE1.attributes.copy()
        attributes.update(
            {
                0x9999: ("error_detected", zigpy.types.Bool, True),
            }
        )

    registry = DeviceRegistry()
    (
        QuirkBuilder("LUMI", "lumi.curtain.agl006")
        .adds(LocalIlluminanceMeasurementCluster)
        .replaces(BasicCluster)
        .replaces(XiaomiPowerConfigurationPercent)
        .replaces(WindowCoveringE1)
        .replaces(FakeXiaomiAqaraDriverE1)
        .removes(FakeXiaomiAqaraDriverE1, cluster_type=ClusterType.Client)
        .enum(
            BasicCluster.AttributeDefs.power_source.name,
            BasicCluster.PowerSource,
            BasicCluster.cluster_id,
            entity_platform=Platform.SENSOR,
            entity_type=EntityType.DIAGNOSTIC,
            translation_key="power_source",
            fallback_name="Power source",
        )
        .enum(
            "hooks_state",
            AqaraE1HookState,
            FakeXiaomiAqaraDriverE1.cluster_id,
            entity_platform=Platform.SENSOR,
            entity_type=EntityType.DIAGNOSTIC,
            translation_key="hooks_state",
            fallback_name="Hooks state",
        )
        .binary_sensor(
            "error_detected",
            FakeXiaomiAqaraDriverE1.cluster_id,
            translation_key="error_detected",
            fallback_name="Error detected",
        )
        .add_to_registry(registry)
    )

    aqara_E1_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.WINDOW_COVERING_DEVICE,
                SIG_EP_INPUT: [
                    zigpy.zcl.clusters.general.Basic.cluster_id,
                    zigpy.zcl.clusters.general.PowerConfiguration.cluster_id,
                    zigpy.zcl.clusters.general.Identify.cluster_id,
                    zigpy.zcl.clusters.general.Time.cluster_id,
                    WindowCoveringE1.cluster_id,
                    XiaomiAqaraDriverE1.cluster_id,
                ],
                SIG_EP_OUTPUT: [
                    zigpy.zcl.clusters.general.Identify.cluster_id,
                    zigpy.zcl.clusters.general.Time.cluster_id,
                    zigpy.zcl.clusters.general.Ota.cluster_id,
                    XiaomiAqaraDriverE1.cluster_id,
                ],
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee="01:2d:6f:00:0a:90:69:e8",
        manufacturer="LUMI",
        model="lumi.curtain.agl006",
        registry=registry,
    )
    aqara_E1_device = registry.resolve(aqara_E1_device)

    aqara_E1_device.endpoints[1].opple_cluster.PLUGGED_ATTR_READS = {
        "hand_open": 0,
        "positions_stored": 0,
        "hooks_lock": 0,
        "hooks_state": AqaraE1HookState.Unlocked,
        "light_level": 0,
        "error_detected": 0,
    }
    update_attribute_cache(aqara_E1_device.endpoints[1].opple_cluster)

    aqara_E1_device.endpoints[1].basic.PLUGGED_ATTR_READS = {
        BasicCluster.AttributeDefs.power_source.name: BasicCluster.PowerSource.Mains_single_phase,
    }
    update_attribute_cache(aqara_E1_device.endpoints[1].basic)

    WCAttrs = zigpy.zcl.clusters.closures.WindowCovering.AttributeDefs
    WCT = zigpy.zcl.clusters.closures.WindowCovering.WindowCoveringType
    WCCS = zigpy.zcl.clusters.closures.WindowCovering.ConfigStatus
    aqara_E1_device.endpoints[1].window_covering.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 0,
        WCAttrs.window_covering_type.name: WCT.Drapery,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    update_attribute_cache(aqara_E1_device.endpoints[1].window_covering)

    zha_device = await join_zigpy_device(zha_gateway, aqara_E1_device)

    power_source_entity = get_entity(
        zha_device,
        platform=Platform.SENSOR,
        exact_entity_type=sensor.EnumSensor,
        qualifier_func=lambda e: e._enum == BasicCluster.PowerSource,
    )
    assert (
        power_source_entity.state.native_value
        == BasicCluster.PowerSource.Mains_single_phase.name
    )

    hook_state_entity = get_entity(
        zha_device,
        platform=Platform.SENSOR,
        exact_entity_type=sensor.EnumSensor,
        qualifier_func=lambda e: e._enum == AqaraE1HookState,
    )
    assert hook_state_entity.state.native_value == AqaraE1HookState.Unlocked.name

    error_detected_entity = get_entity(
        zha_device,
        platform=Platform.BINARY_SENSOR,
        exact_entity_type=binary_sensor.BinarySensor,
        qualifier_func=lambda e: e._attribute_name == "error_detected",
    )
    assert error_detected_entity.state.is_on is False


def _get_test_device(
    zha_gateway: Gateway,
    manufacturer: str,
    model: str,
    augment_method: Callable[[QuirkBuilder], QuirkBuilder] | None = None,
):
    registry = DeviceRegistry()
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    zigpy.zcl.clusters.general.PowerConfiguration.cluster_id,
                    zigpy.zcl.clusters.general.Groups.cluster_id,
                    zigpy.zcl.clusters.general.OnOff.cluster_id,
                ],
                SIG_EP_OUTPUT: [
                    zigpy.zcl.clusters.general.Scenes.cluster_id,
                ],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.NON_COLOR_CONTROLLER,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee="01:2d:6f:00:0a:90:69:e8",
        manufacturer=manufacturer,
        model=model,
        registry=registry,
    )

    quirk_builder = (
        QuirkBuilder(manufacturer, model)
        .replaces(PowerConfig1CRCluster)
        .replaces(ScenesCluster, cluster_type=ClusterType.Client)
        .number(
            zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            zigpy.zcl.clusters.general.OnOff.cluster_id,
            endpoint_id=3,
            min_value=1,
            max_value=100,
            step=1,
            unit=UnitOfTime.SECONDS,
            multiplier=1,
            translation_key="on_off_transition_time",
            fallback_name="On off transition time",
        )
        .number(
            zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            zigpy.zcl.clusters.general.Time.cluster_id,
            min_value=1,
            max_value=100,
            step=1,
            unit=UnitOfTime.SECONDS,
            multiplier=1,
            translation_key="on_off_transition_time",
            fallback_name="On off transition time",
        )
        .sensor(
            zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            zigpy.zcl.clusters.general.OnOff.cluster_id,
            entity_type=EntityType.CONFIG,
            translation_key="analog_input",
            fallback_name="Analog input",
        )
    )

    if augment_method:
        quirk_builder = augment_method(quirk_builder)

    quirk_builder.add_to_registry(registry)

    zigpy_device = registry.resolve(zigpy_device)
    zigpy_device.endpoints[1].power.PLUGGED_ATTR_READS = {
        "battery_voltage": 3,
        "battery_percentage_remaining": 100,
    }
    update_attribute_cache(zigpy_device.endpoints[1].power)
    zigpy_device.endpoints[1].on_off.PLUGGED_ATTR_READS = {
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name: 3,
    }
    update_attribute_cache(zigpy_device.endpoints[1].on_off)
    return zigpy_device


async def test_quirks_v2_entity_no_metadata(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test quirks v2 discovery skipped - no metadata."""

    zigpy_device = _get_test_device(
        zha_gateway, "Ikea of Sweden2", "TRADFRI remote control2"
    )
    entry = getattr(zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR)
    factory = entry.zha_device_factory
    new_factory = dataclasses.replace(
        factory,
        quirk_definition=attrs.evolve(factory.quirk_definition, entity_metadata=()),
    )
    setattr(
        zigpy_device,
        QUIRK_REGISTRY_ENTRY_ATTR,
        dataclasses.replace(entry, zha_device_factory=new_factory),
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    assert (
        f"Device: {str(zigpy_device.ieee)}-{zha_device.name} does not expose any quirks v2 entities"
        in caplog.text
    )


async def test_quirks_v2_entity_discovery_errors(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test quirks v2 discovery skipped - errors."""

    zigpy_device = _get_test_device(
        zha_gateway, "Ikea of Sweden3", "TRADFRI remote control3"
    )

    # Inject unknown quirks v2 entity metadata
    class UnknownEntityMetadata:
        endpoint_id = 1
        cluster_id = zigpy.zcl.clusters.general.OnOff.cluster_id
        cluster_type = ClusterType.Server
        entity_platform = Platform.UPDATE

    entry = getattr(zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR)
    factory = entry.zha_device_factory
    new_factory = dataclasses.replace(
        factory,
        quirk_definition=attrs.evolve(
            factory.quirk_definition,
            entity_metadata=(
                *factory.quirk_definition.entity_metadata,
                UnknownEntityMetadata(),
            ),
        ),
    )
    setattr(
        zigpy_device,
        QUIRK_REGISTRY_ENTRY_ATTR,
        dataclasses.replace(entry, zha_device_factory=new_factory),
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert (
        f"Device: {zigpy_device.ieee}-{zha_device.name} does not have an"
        " endpoint with id: 3 - unable to create entity with metadata:"
    ) in caplog.text

    time_cluster_id = zigpy.zcl.clusters.general.Time.cluster_id

    assert (
        f"Device: {zigpy_device.ieee}-{zha_device.name} does not have a"
        f" cluster with id: {time_cluster_id} - unable to create entity with"
        " metadata:"
    ) in caplog.text

    device_info = f"{zigpy_device.ieee}-{zha_device.name}"
    device_regex = (
        rf"Device: {re.escape(device_info)} has an entity with metadata: (.*?) that"
        rf" does not have an entity class mapping - unable to create entity"
    )
    assert re.search(device_regex, caplog.text)


DEVICE_CLASS_TYPES = [NumberMetadata, BinarySensorMetadata, ZCLSensorMetadata]


class BadDeviceClass(enum.Enum):
    """Bad device class."""

    BAD = "bad"


def bad_binary_sensor_device_class(
    quirk_builder: QuirkBuilder,
) -> QuirkBuilder:
    """Introduce a bad device class on a binary sensor."""

    return quirk_builder.binary_sensor(
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.on_off.name,
        zigpy.zcl.clusters.general.OnOff.cluster_id,
        translation_key="on_off",
        fallback_name="On off",
        device_class=BadDeviceClass.BAD,
    )


def bad_sensor_device_class(
    quirk_builder: QuirkBuilder,
) -> QuirkBuilder:
    """Introduce a bad device class on a sensor."""

    return quirk_builder.sensor(
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
        zigpy.zcl.clusters.general.OnOff.cluster_id,
        translation_key="off_wait_time",
        fallback_name="Off wait time",
        device_class=BadDeviceClass.BAD,
    )


def bad_number_device_class(
    quirk_builder: QuirkBuilder,
) -> QuirkBuilder:
    """Introduce a bad device class on a number."""

    return quirk_builder.number(
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.on_time.name,
        zigpy.zcl.clusters.general.OnOff.cluster_id,
        translation_key="on_time",
        fallback_name="On time",
        device_class=BadDeviceClass.BAD,
    )


ERROR_ROOT = "Quirks provided an invalid device class"


@pytest.mark.parametrize(
    ("augment_method", "expected_exception_string"),
    [
        (
            bad_binary_sensor_device_class,
            f"{ERROR_ROOT}: BadDeviceClass.BAD for platform binary_sensor",
        ),
        (
            bad_sensor_device_class,
            f"{ERROR_ROOT}: BadDeviceClass.BAD for platform sensor",
        ),
        (
            bad_number_device_class,
            f"{ERROR_ROOT}: BadDeviceClass.BAD for platform number",
        ),
    ],
)
async def test_quirks_v2_metadata_bad_device_classes(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    caplog: pytest.LogCaptureFixture,
    augment_method: Callable[[QuirkBuilder], QuirkBuilder],
    expected_exception_string: str,
) -> None:
    """Test bad quirks v2 device classes."""

    # introduce an error
    zigpy_device = _get_test_device(
        zha_gateway,
        "Ikea of Sweden5",
        "TRADFRI remote control5",
        augment_method=augment_method,
    )
    await join_zigpy_device(zha_gateway, zigpy_device)

    assert expected_exception_string in caplog.text


async def test_quirks_v2_fallback_name(zha_gateway: Gateway) -> None:
    """Test quirks v2 fallback name."""

    zigpy_device = _get_test_device(
        zha_gateway,
        "Ikea of Sweden6",
        "TRADFRI remote control6",
        augment_method=lambda builder: builder.sensor(
            attribute_name=zigpy.zcl.clusters.general.OnOff.AttributeDefs.global_scene_control.name,
            cluster_id=zigpy.zcl.clusters.general.OnOff.cluster_id,
            translation_key="some_sensor",
            fallback_name="Fallback name",
        ),
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(
        zha_device,
        platform=Platform.SENSOR,
        qualifier_func=lambda e: e.fallback_name == "Fallback name",
    )
    assert entity.fallback_name == "Fallback name"


async def test_device_match_firmware_version(zha_gateway: Gateway) -> None:
    """Test DeviceMatch firmware-version filtering against the OTA file version."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [zigpy.zcl.clusters.general.Basic.cluster_id],
                SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.PUMP,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        manufacturer="Some Manufacturer",
        model="Some Model",
    )
    ota = zigpy_device.endpoints[1].out_clusters[
        zigpy.zcl.clusters.general.Ota.cluster_id
    ]
    ota.update_attribute(
        zigpy.zcl.clusters.general.Ota.AttributeDefs.current_file_version.id, 0x12345678
    )

    applies_to = (ModelInfo("Some Manufacturer", "Some Model"),)

    # In range [min, max)
    assert DeviceMatch(
        applies_to=applies_to,
        firmware_version_min=0x12345678,
        firmware_version_max=0x12345679,
    ).matches(zigpy_device)

    # Below min
    assert not DeviceMatch(
        applies_to=applies_to, firmware_version_min=0x12345679
    ).matches(zigpy_device)

    # max is exclusive
    assert not DeviceMatch(
        applies_to=applies_to, firmware_version_max=0x12345678
    ).matches(zigpy_device)

    # Missing firmware version honors `allow_missing`
    no_ota_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [zigpy.zcl.clusters.general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.PUMP,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        manufacturer="Some Manufacturer",
        model="Some Model",
        ieee="01:2d:6f:00:0a:90:69:e9",
    )
    assert DeviceMatch(
        applies_to=applies_to,
        firmware_version_min=0x12345678,
        firmware_version_allow_missing=True,
    ).matches(no_ota_device)
    assert not DeviceMatch(
        applies_to=applies_to,
        firmware_version_min=0x12345678,
        firmware_version_allow_missing=False,
    ).matches(no_ota_device)


def pytest_generate_tests(metafunc):
    """Generate tests for all device files."""
    if "file_path" in metafunc.fixturenames:
        # use the filename as ID for better test names
        file_paths = sorted(pathlib.Path("tests/data/devices").glob("**/*.json"))
        file_paths = [
            f for f in file_paths if f.name != "lumi-lumi-motion-agl04.json"
        ]  # TODO: fix lingering timer for `_Motion._turn_off` in quirks

        metafunc.parametrize("file_path", file_paths, ids=[f.name for f in file_paths])


async def test_devices_from_files(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    file_path: pathlib.Path,
) -> None:
    """Test all devices."""
    with mock.patch(
        "zigpy.zcl.clusters.general.Identify.request",
        new=AsyncMock(return_value=[mock.sentinel.data, zcl_f.Status.SUCCESS]),
    ):
        device_data_text = await asyncio.get_running_loop().run_in_executor(
            None, file_path.read_text
        )
        device_data = json.loads(device_data_text)

        zigpy_device = zigpy_device_from_device_data(
            app=zha_gateway.application_controller, device_data=device_data
        )

        # XXX: attribute updates during device initialization unfortunately triggers
        # logic within quirks to "fix" attributes. Since these attributes are *read out*
        # in this state, this will compound the "fix" repeatedly.
        with (
            mock.patch("zigpy.zcl.Cluster._update_attribute"),
            mock.patch("zigpy.zcl.helpers.AttributeCache.set_value"),
        ):
            zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
            await zha_gateway.async_block_till_done(wait_background_tasks=True)
            assert zha_device is not None

        # Ensure entity recomputation is idempotent
        await zha_device.recompute_entities()

        unique_id_collisions = defaultdict(list)
        for entity in zha_device.platform_entities.values():
            unique_id_collisions[entity.unique_id].append(entity)

        for unique_id, entities in unique_id_collisions.items():
            if len(entities) == 1:
                continue

            prefixed_unique_ids = [
                f"{entity.PLATFORM.name.lower()}.{entity.unique_id}"
                for entity in entities
            ]

            if len(set(prefixed_unique_ids)) != len(entities):
                raise ValueError(
                    f"Duplicate unique_id {unique_id} found in entities: {entities}"
                )
            else:
                warnings.warn(
                    f"Unique IDs are unique only with platform prefix: {dict(zip(prefixed_unique_ids, entities))}"
                )

        unique_id_migrations: dict[tuple[Platform, str], PlatformEntity] = {}
        for entity in zha_device.platform_entities.values():
            for old_unique_id in entity.migrate_unique_ids:
                key = (entity.PLATFORM, old_unique_id)
                if key in unique_id_migrations:
                    raise ValueError(
                        f"Duplicate unique_id {key} found in migration: "
                        f"{unique_id_migrations[key]} and {entity}"
                    )

                unique_id_migrations[key] = entity

        # XXX: We re-serialize the JSON because integer enum types are converted when
        # serializing but will not compare properly otherwise
        loaded_device_data = json.loads(
            json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
        )

        # The quirk class path varies with the quirks implementation (v2 quirks
        # used to all be `zigpy.quirks.v2.CustomZigpyDevice`, compiled ZHA quirks
        # name the defining module); `quirk_applied` still has to match.
        del loaded_device_data["quirk_class"]
        del device_data["quirk_class"]

        assert loaded_device_data == device_data

        # Assert identify called on join for devices that support it
        cluster_identify = _get_identify_cluster(zha_device.device)
        if cluster_identify and not zha_device.skip_configuration:
            assert cluster_identify.request.mock_calls == [
                mock.call(
                    False,
                    cluster_identify.commands_by_name["trigger_effect"].id,
                    cluster_identify.commands_by_name["trigger_effect"].schema,
                    effect_id=zigpy.zcl.clusters.general.Identify.EffectIdentifier.Okay,
                    effect_variant=(
                        zigpy.zcl.clusters.general.Identify.EffectVariant.Default
                    ),
                    # enhance this maybe by looking at disable default response?
                    expect_reply=(
                        cluster_identify.endpoint.model
                        not in ("HDC52EastwindFan", "HBUniversalCFRemote")
                    ),
                    manufacturer=None,
                )
            ]

        await zha_device.on_remove()


async def test_skip_configuration_skips_bind_and_reporting(
    zha_gateway: Gateway,
) -> None:
    """A device marked skip_configuration must not have binds or reporting set up."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/lumi-lumi-weather.json",
    )
    assert zigpy_device.skip_configuration is True

    bind_mocks = []
    reporting_mocks = []
    with contextlib.ExitStack() as stack:
        for ep in zigpy_device.non_zdo_endpoints:
            for cluster in list(ep.in_clusters.values()) + list(
                ep.out_clusters.values()
            ):
                bind_mocks.append(
                    stack.enter_context(
                        mock.patch.object(cluster, "bind", wraps=cluster.bind)
                    )
                )
                reporting_mocks.append(
                    stack.enter_context(
                        mock.patch.object(
                            cluster,
                            "configure_reporting_multiple",
                            wraps=cluster.configure_reporting_multiple,
                        )
                    )
                )

        zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
        await zha_device.async_configure()

    assert all(m.mock_calls == [] for m in bind_mocks)
    assert all(m.mock_calls == [] for m in reporting_mocks)


async def test_get_diagnostics_json_repeated_calls(zha_gateway: Gateway) -> None:
    """Test that calling get_diagnostics_json twice produces the same result."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/jasco-products-45856-0x00000006.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    first = json.loads(
        json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
    )
    second = json.loads(
        json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
    )
    assert first == second


async def test_diagnostics_includes_ota_last_query_cmd(zha_gateway: Gateway) -> None:
    """Test that diagnostics includes last_query_cmd for OTA clusters."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/ikea-of-sweden-tradfri-bulb-gu10-ws-400lm-0x23095631.json",
    )

    ota_cluster = zigpy_device.endpoints[1].out_clusters[Ota.cluster_id]
    ota_cluster.last_query_cmd = QueryNextImageCommand(
        field_control=0,
        manufacturer_code=0x117C,
        image_type=0x1234,
        current_file_version=0x00AABBCC,
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    diag = json.loads(json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder))

    ota_diag = next(
        c for c in diag["endpoints"]["1"]["out_clusters"] if c["cluster_id"] == "0x0019"
    )

    assert ota_diag["last_query_cmd"] == {
        "manufacturer_code": 0x117C,
        "image_type": 0x1234,
        "current_file_version": 0x00AABBCC,
        "hardware_version": None,
    }


async def test_diagnostics_omits_ota_last_query_cmd_when_none(
    zha_gateway: Gateway,
) -> None:
    """Test that diagnostics omits last_query_cmd when it is None."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/ikea-of-sweden-tradfri-bulb-gu10-ws-400lm-0x23095631.json",
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    diag = json.loads(json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder))

    ota_diag = next(
        c for c in diag["endpoints"]["1"]["out_clusters"] if c["cluster_id"] == "0x0019"
    )

    assert "last_query_cmd" not in ota_diag


async def test_entityless_cluster_binds_via_virtual_entity(
    zha_gateway: Gateway,
) -> None:
    """Manufacturer clusters that don't produce entities are still bound."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/signify-netherlands-b-v-rwl022-0x02004d27.json",
    )

    # The Philips remote cluster (0xFC00) has no HA entity but `PhilipsRemoteBind`
    # virtual entity binds it so the device can send commands to the coordinator.
    philips_cluster = zigpy_device.endpoints[1].in_clusters[PHILIPS_REMOTE_CLUSTER]

    await join_zigpy_device(zha_gateway, zigpy_device)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert len(philips_cluster.bind.mock_calls) == 1
