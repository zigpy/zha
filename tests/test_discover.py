"""Test ZHA device discovery."""

import asyncio
from collections import defaultdict
from collections.abc import Callable
import enum
import json
import pathlib
import re
from unittest import mock
from unittest.mock import AsyncMock, call
import warnings

import pytest
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
import zigpy.quirks
from zigpy.quirks.v2 import (
    BinarySensorMetadata,
    EntityType,
    NumberMetadata,
    QuirkBuilder,
    ZCLSensorMetadata,
)
from zigpy.quirks.v2.homeassistant import UnitOfTime
import zigpy.types
from zigpy.zcl import ClusterType
import zigpy.zcl.clusters.closures
import zigpy.zcl.clusters.general
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
)
from zha.application import Platform
from zha.application.discovery import ENDPOINT_PROBE, EndpointProbe
from zha.application.gateway import Gateway
from zha.application.helpers import DeviceOverridesConfiguration
from zha.application.platforms import PlatformEntity, binary_sensor, sensor
from zha.application.registries import SINGLE_INPUT_CLUSTER_DEVICE_CLASS
from zha.zigbee.cluster_handlers import ClusterHandler
from zha.zigbee.endpoint import Endpoint


def _get_identify_cluster(zigpy_device):
    for endpoint in list(zigpy_device.endpoints.values())[1:]:
        if hasattr(endpoint, "identify"):
            return endpoint.identify


@mock.patch("zha.application.discovery.EndpointProbe.discover_by_device_type")
@mock.patch("zha.application.discovery.EndpointProbe.discover_by_cluster_id")
def test_discover_entities(m1, m2) -> None:
    """Test discover endpoint class method."""
    endpoint = mock.MagicMock()
    endpoint.device.is_coordinator = False

    for _entity in ENDPOINT_PROBE.discover_entities(endpoint, device_overrides={}):
        pass

    assert m1.call_count == 1
    assert m1.call_args[0][0] is endpoint
    assert m2.call_count == 1
    assert m2.call_args[0][0] is endpoint


@pytest.mark.parametrize(
    ("device_type", "platform", "hit"),
    [
        (zigpy.profiles.zha.DeviceType.ON_OFF_LIGHT, Platform.LIGHT, True),
        (zigpy.profiles.zha.DeviceType.ON_OFF_BALLAST, Platform.SWITCH, True),
        (zigpy.profiles.zha.DeviceType.SMART_PLUG, Platform.SWITCH, True),
        (0xFFFF, None, False),
    ],
)
def test_discover_by_device_type(device_type, platform, hit) -> None:
    """Test entity discovery by device type."""

    endpoint = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = device_type
    type(endpoint).zigpy_endpoint = ep_mock

    entity_cls = mock.MagicMock()

    get_entity_mock = mock.MagicMock(return_value=(entity_cls, mock.sentinel.claimed))
    with mock.patch(
        "zha.application.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        entities = list(
            ENDPOINT_PROBE.discover_by_device_type(endpoint, device_overrides={})
        )

    if hit:
        assert len(entities) == 1
        assert entity_cls.mock_calls == [
            call(
                endpoint=endpoint,
                device=endpoint.device,
                cluster_handlers=mock.sentinel.claimed,
                legacy_discovery_unique_id=f"{endpoint.device.ieee}-{endpoint.id}",
            )
        ]
    else:
        assert not entities
        assert entity_cls.mock_calls == []


def test_discover_by_device_type_override() -> None:
    """Test entity discovery by device type overriding."""

    device = mock.MagicMock()
    device.ieee = zigpy.types.EUI64.convert("00:11:22:33:44:55:66:77")

    endpoint = mock.MagicMock(spec_set=Endpoint)
    endpoint.id = 1
    endpoint.device = device

    entity_cls = mock.MagicMock()

    get_entity_mock = mock.MagicMock(return_value=(entity_cls, mock.sentinel.claimed))
    with (
        mock.patch(
            "zha.application.registries.PLATFORM_ENTITIES.get_entity",
            get_entity_mock,
        ),
    ):
        entities = list(
            ENDPOINT_PROBE.discover_by_device_type(
                endpoint,
                device_overrides={
                    "00:11:22:33:44:55:66:77-1": DeviceOverridesConfiguration(
                        type=Platform.SIREN
                    )
                },
            )
        )

        assert len(entities) == 1
        assert entity_cls.mock_calls == [
            call(
                endpoint=endpoint,
                device=device,
                cluster_handlers=mock.sentinel.claimed,
                legacy_discovery_unique_id="00:11:22:33:44:55:66:77-1",
            )
        ]

        assert get_entity_mock.mock_calls[0].args[0] == Platform.SIREN


def test_discover_probe_single_cluster() -> None:
    """Test entity discovery by single cluster."""

    endpoint = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = 0x0100
    type(endpoint).zigpy_endpoint = ep_mock

    entity_cls = mock.MagicMock()
    get_entity_mock = mock.MagicMock(return_value=(entity_cls, mock.sentinel.claimed))
    cluster_handler_mock = mock.MagicMock(spec_set=ClusterHandler)
    with mock.patch(
        "zha.application.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        for _entity in ENDPOINT_PROBE.probe_single_cluster(
            Platform.SWITCH, cluster_handler_mock, endpoint
        ):
            pass

    assert entity_cls.mock_calls == [
        call(
            endpoint=endpoint,
            device=endpoint.device,
            cluster_handlers=mock.sentinel.claimed,
            legacy_discovery_unique_id=f"{endpoint.device.ieee}-{endpoint.id}-{cluster_handler_mock.cluster.cluster_id}",
        )
    ]

    assert get_entity_mock.mock_calls[0].args[0] == Platform.SWITCH


def _ch_mock(cluster):
    """Return mock of a cluster_handler with a cluster."""
    cluster_handler = mock.MagicMock()
    type(cluster_handler).cluster = mock.PropertyMock(
        return_value=cluster(mock.MagicMock())
    )
    return cluster_handler


def test_single_input_cluster_device_class_by_cluster_class() -> None:
    """Test SINGLE_INPUT_CLUSTER_DEVICE_CLASS matching by cluster id or class."""

    class QuirkedIAS(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.security.IasZone):
        """Quirked IAS Zone cluster."""

    class _Analog(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.general.AnalogInput):
        pass

    door_ch = _ch_mock(zigpy.zcl.clusters.closures.DoorLock)
    cover_ch = _ch_mock(zigpy.zcl.clusters.closures.WindowCovering)
    multistate_ch = _ch_mock(zigpy.zcl.clusters.general.MultistateInput)
    ias_ch = _ch_mock(QuirkedIAS)
    analog_ch = _ch_mock(_Analog)

    endpoint = mock.MagicMock(spec_set=Endpoint)
    endpoint.unclaimed_cluster_handlers.return_value = [
        door_ch,
        cover_ch,
        multistate_ch,
        ias_ch,
        analog_ch,
    ]

    with (
        mock.patch.dict(
            SINGLE_INPUT_CLUSTER_DEVICE_CLASS,
            {
                zigpy.zcl.clusters.closures.DoorLock.cluster_id: Platform.LOCK,
                zigpy.zcl.clusters.closures.WindowCovering.cluster_id: Platform.COVER,
                zigpy.zcl.clusters.general.AnalogInput.cluster_id: Platform.SENSOR,
                zigpy.zcl.clusters.general.MultistateInput.cluster_id: Platform.SENSOR,
                zigpy.zcl.clusters.security.IasZone.cluster_id: Platform.BINARY_SENSOR,
            },
            clear=True,
        ),
        mock.patch(
            "zha.application.discovery.EndpointProbe.probe_single_cluster",
            new=mock.MagicMock(),
        ) as probe_mock,
    ):
        for _entity in EndpointProbe().discover_by_cluster_id(endpoint):
            pass

        assert probe_mock.call_count == len(endpoint.unclaimed_cluster_handlers())
        assert [m for m in probe_mock.mock_calls if m != call().__iter__()] == [
            call(Platform.LOCK, door_ch, endpoint),
            call(Platform.COVER, cover_ch, endpoint),
            call(Platform.SENSOR, multistate_ch, endpoint),
            call(Platform.BINARY_SENSOR, ias_ch, endpoint),
            call(Platform.SENSOR, analog_ch, endpoint),
        ]


@pytest.mark.parametrize("override", [None, "switch"])
async def test_device_override(
    zha_gateway: Gateway,
    override: str | None,
) -> None:
    """Test device discovery override."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                "endpoint_id": 1,
                SIG_EP_INPUT: [0, 3, 4, 5, 6, 8, 768, 2821, 64513],
                SIG_EP_OUTPUT: [25],
                SIG_EP_PROFILE: 260,
            }
        },
        "00:11:22:33:44:55:66:77",
        "manufacturer",
        "model",
        patch_cluster=False,
    )

    if override is not None:
        overrides = {
            "00:11:22:33:44:55:66:77-1": DeviceOverridesConfiguration(type=override)
        }
        zha_gateway.config.config.device_overrides = overrides

    await zha_gateway.async_device_initialized(zigpy_device)
    await zha_gateway.async_block_till_done()
    zha_device = zha_gateway.get_device(zigpy_device.ieee)

    get_entity(zha_device, platform=Platform.SWITCH if override else Platform.LIGHT)


async def test_quirks_v2_entity_discovery(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test quirks v2 discovery."""

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
    )

    (
        QuirkBuilder(
            "Ikea of Sweden", "TRADFRI remote control", zigpy.quirks._DEVICE_REGISTRY
        )
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
            translation_key="off_wait_time",
            fallback_name="Off wait time",
        )
        .add_to_registry()
    )

    zigpy_device = zigpy.quirks._DEVICE_REGISTRY.get_device(zigpy_device)
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

    get_entity(zha_device, platform=Platform.NUMBER)


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
        .add_to_registry()
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
    )
    aqara_E1_device = zigpy.quirks._DEVICE_REGISTRY.get_device(aqara_E1_device)

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
        power_source_entity.state["state"]
        == BasicCluster.PowerSource.Mains_single_phase.name
    )

    hook_state_entity = get_entity(
        zha_device,
        platform=Platform.SENSOR,
        exact_entity_type=sensor.EnumSensor,
        qualifier_func=lambda e: e._enum == AqaraE1HookState,
    )
    assert hook_state_entity.state["state"] == AqaraE1HookState.Unlocked.name

    error_detected_entity = get_entity(
        zha_device,
        platform=Platform.BINARY_SENSOR,
        exact_entity_type=binary_sensor.BinarySensor,
        qualifier_func=lambda e: e._attribute_name == "error_detected",
    )
    assert error_detected_entity.state["state"] is False


def _get_test_device(
    zha_gateway: Gateway,
    manufacturer: str,
    model: str,
    augment_method: Callable[[QuirkBuilder], QuirkBuilder] | None = None,
):
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
    )

    quirk_builder = (
        QuirkBuilder(manufacturer, model, zigpy.quirks._DEVICE_REGISTRY)
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

    quirk_builder.add_to_registry()

    zigpy_device = zigpy.quirks._DEVICE_REGISTRY.get_device(zigpy_device)
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
    setattr(zigpy_device, "_exposes_metadata", {})
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
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert (
        f"Device: {zigpy_device.ieee}-{zha_device.name} does not have an"
        " endpoint with id: 3 - unable to create entity with"
        " cluster details: (3, 6, <ClusterType.Server: 0>)"
    ) in caplog.text

    time_cluster_id = zigpy.zcl.clusters.general.Time.cluster_id

    assert (
        f"Device: {zigpy_device.ieee}-{zha_device.name} does not have a"
        f" cluster with id: {time_cluster_id} - unable to create entity with"
        f" cluster details: (1, {time_cluster_id}, <ClusterType.Server: 0>)"
    ) in caplog.text

    device_info = f"{zigpy_device.ieee}-{zha_device.name}"
    device_regex = (
        rf"Device: {re.escape(device_info)} has an entity with details: (.*?) that"
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

    # remove the device so we don't pollute the rest of the tests
    zigpy.quirks._DEVICE_REGISTRY.remove(zigpy_device)


async def test_quirks_v2_fallback_name(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test quirks v2 fallback name."""

    zigpy_device = _get_test_device(
        zha_gateway,
        "Ikea of Sweden6",
        "TRADFRI remote control6",
        augment_method=lambda builder: builder.sensor(
            attribute_name=zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
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
        with mock.patch("zigpy.zcl.Cluster._update_attribute"):
            zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
            await zha_gateway.async_block_till_done(wait_background_tasks=True)
            assert zha_device is not None

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

        await zha_device.on_remove()

        # XXX: We re-serialize the JSON because integer enum types are converted when
        # serializing but will not compare properly otherwise
        loaded_device_data = json.loads(
            json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
        )
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
                    tsn=None,
                )
            ]
