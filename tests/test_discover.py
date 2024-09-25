"""Test ZHA device discovery."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import enum
import itertools
import json
import pathlib
import re
from typing import Any, Final
from unittest import mock
from unittest.mock import AsyncMock, patch

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
from zigpy.const import SIG_ENDPOINTS, SIG_MANUFACTURER, SIG_MODEL, SIG_NODE_DESC
import zigpy.device
import zigpy.profiles.zha
import zigpy.quirks
from zigpy.quirks.v2 import (
    BinarySensorMetadata,
    EntityMetadata,
    EntityType,
    NumberMetadata,
    QuirkBuilder,
    QuirksV2RegistryEntry,
    ZCLCommandButtonMetadata,
    ZCLSensorMetadata,
)
from zigpy.quirks.v2.homeassistant import UnitOfTime
import zigpy.types
from zigpy.zcl import ClusterType
import zigpy.zcl.clusters.closures
import zigpy.zcl.clusters.general
import zigpy.zcl.clusters.security
import zigpy.zcl.foundation as zcl_f
import zigpy.zdo.types as zdo_t

from tests.common import get_entity, update_attribute_cache
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform, discovery
from zha.application.discovery import ENDPOINT_PROBE, PLATFORMS, EndpointProbe
from zha.application.gateway import Gateway
from zha.application.helpers import DeviceOverridesConfiguration
from zha.application.platforms import PlatformEntity, binary_sensor, sensor
from zha.application.registries import (
    PLATFORM_ENTITIES,
    SINGLE_INPUT_CLUSTER_DEVICE_CLASS,
)
from zha.zigbee.cluster_handlers import ClusterHandler
from zha.zigbee.device import Device
from zha.zigbee.endpoint import Endpoint

from .zha_devices_list import (
    DEV_SIG_ATTRIBUTES,
    DEV_SIG_CLUSTER_HANDLERS,
    DEV_SIG_ENT_MAP,
    DEV_SIG_ENT_MAP_CLASS,
    DEV_SIG_ENT_MAP_ID,
    DEV_SIG_EVT_CLUSTER_HANDLERS,
    DEVICES,
)

NO_TAIL_ID = re.compile("_\\d$")
UNIQUE_ID_HD = re.compile(r"^(([\da-fA-F]{2}:){7}[\da-fA-F]{2}-\d{1,3})", re.X)
STATE_OFF: Final[str] = "off"

IGNORE_SUFFIXES = [
    zigpy.zcl.clusters.general.OnOff.StartUpOnOff.__name__,
    "on_off_transition_time",
    "on_level",
    "on_transition_time",
    "off_transition_time",
    "default_move_rate",
    "start_up_current_level",
    "counter",
]


def contains_ignored_suffix(unique_id: str) -> bool:
    """Return true if the unique_id ends with an ignored suffix."""
    return any(suffix.lower() in unique_id.lower() for suffix in IGNORE_SUFFIXES)


@pytest.fixture
def zha_device_mock(
    zigpy_device_mock: Callable[..., zigpy.device.Device],
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
) -> Callable[..., Coroutine[Any, Any, Device]]:
    """Mock device factory."""

    async def _mock(
        endpoints,
        ieee="00:11:22:33:44:55:66:77",
        manufacturer="mock manufacturer",
        model="mock model",
        node_desc=None,
        patch_cluster=False,
    ):
        return await device_joined(
            zigpy_device_mock(
                endpoints,
                ieee=ieee,
                manufacturer=manufacturer,
                model=model,
                node_descriptor=node_desc,
                patch_cluster=patch_cluster,
            )
        )

    return _mock


@patch(
    "zigpy.zcl.clusters.general.Identify.request",
    new=AsyncMock(return_value=[mock.sentinel.data, zcl_f.Status.SUCCESS]),
)
@pytest.mark.parametrize("device", DEVICES)
async def test_devices(
    device,
    zha_gateway: Gateway,
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
) -> None:
    """Test device discovery."""
    zigpy_device = zigpy_device_mock(
        endpoints=device[SIG_ENDPOINTS],
        ieee="00:11:22:33:44:55:66:77",
        manufacturer=device[SIG_MANUFACTURER],
        model=device[SIG_MODEL],
        node_descriptor=zdo_t.NodeDescriptor(**device[SIG_NODE_DESC]),
        attributes=device.get(DEV_SIG_ATTRIBUTES),
        patch_cluster=False,
    )

    cluster_identify = _get_identify_cluster(zigpy_device)
    if cluster_identify:
        cluster_identify.request.reset_mock()

    zha_dev: Device = await device_joined(zigpy_device)
    await zha_gateway.async_block_till_done()

    if cluster_identify and not zha_dev.skip_configuration:
        assert cluster_identify.request.mock_calls == [
            mock.call(
                False,
                cluster_identify.commands_by_name["trigger_effect"].id,
                cluster_identify.commands_by_name["trigger_effect"].schema,
                effect_id=zigpy.zcl.clusters.general.Identify.EffectIdentifier.Okay,
                effect_variant=(
                    zigpy.zcl.clusters.general.Identify.EffectVariant.Default
                ),
                expect_reply=True,
                manufacturer=None,
                tsn=None,
            )
        ]

    event_cluster_handlers = {
        ch.id
        for endpoint in zha_dev._endpoints.values()
        for ch in endpoint.client_cluster_handlers.values()
    }
    assert event_cluster_handlers == set(device[DEV_SIG_EVT_CLUSTER_HANDLERS])
    # we need to probe the class create entity factory so we need to reset this to get accurate results
    PLATFORM_ENTITIES.clean_up()

    # Keep track of unhandled entities: they should always be ones we explicitly ignore
    created_entities: dict[str, PlatformEntity] = {}
    for dev in zha_gateway.devices.values():
        for entity in dev.platform_entities.values():
            if entity.device.ieee == zigpy_device.ieee:
                created_entities[entity.unique_id] = entity

    unhandled_entities = set(created_entities.keys())

    for (platform, unique_id), ent_info in device[DEV_SIG_ENT_MAP].items():
        no_tail_id = NO_TAIL_ID.sub("", ent_info[DEV_SIG_ENT_MAP_ID])
        message1 = f"No entity found for platform[{platform}] unique_id[{unique_id}] no_tail_id[{no_tail_id}]"

        if not contains_ignored_suffix(unique_id):
            assert unique_id in created_entities, message1
            entity = created_entities[unique_id]
            unhandled_entities.remove(unique_id)

            assert platform == entity.PLATFORM
            assert type(entity).__name__ == ent_info[DEV_SIG_ENT_MAP_CLASS]
            # unique_id used for discover is the same for "multi entities"
            assert unique_id == entity.unique_id
            assert {ch.name for ch in entity.cluster_handlers.values()} == set(
                ent_info[DEV_SIG_CLUSTER_HANDLERS]
            )

    # All unhandled entities should be ones we explicitly ignore
    for unique_id in unhandled_entities:
        platform = created_entities[unique_id].PLATFORM
        assert platform in PLATFORMS
        assert contains_ignored_suffix(unique_id)


def _get_identify_cluster(zigpy_device):
    for endpoint in list(zigpy_device.endpoints.values())[1:]:
        if hasattr(endpoint, "identify"):
            return endpoint.identify


@mock.patch("zha.application.discovery.EndpointProbe.discover_by_device_type")
@mock.patch("zha.application.discovery.EndpointProbe.discover_by_cluster_id")
def test_discover_entities(m1, m2) -> None:
    """Test discover endpoint class method."""
    endpoint = mock.MagicMock()
    ENDPOINT_PROBE.discover_entities(endpoint)
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

    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    with mock.patch(
        "zha.application.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        ENDPOINT_PROBE.discover_by_device_type(endpoint)
    if hit:
        assert get_entity_mock.call_count == 1
        assert endpoint.claim_cluster_handlers.call_count == 1
        assert endpoint.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
        assert endpoint.async_new_entity.call_count == 1
        assert endpoint.async_new_entity.call_args[0][0] == platform
        assert endpoint.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls


def test_discover_by_device_type_override() -> None:
    """Test entity discovery by device type overriding."""

    endpoint = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = 0x0100
    type(endpoint).zigpy_endpoint = ep_mock

    overrides = {endpoint.unique_id: DeviceOverridesConfiguration(type=Platform.SWITCH)}
    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    with (
        mock.patch(
            "zha.application.registries.PLATFORM_ENTITIES.get_entity",
            get_entity_mock,
        ),
        mock.patch.dict(ENDPOINT_PROBE._device_configs, overrides, clear=True),
    ):
        ENDPOINT_PROBE.discover_by_device_type(endpoint)
        assert get_entity_mock.call_count == 1
        assert endpoint.claim_cluster_handlers.call_count == 1
        assert endpoint.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
        assert endpoint.async_new_entity.call_count == 1
        assert endpoint.async_new_entity.call_args[0][0] == Platform.SWITCH
        assert endpoint.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls


def test_discover_probe_single_cluster() -> None:
    """Test entity discovery by single cluster."""

    endpoint = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = 0x0100
    type(endpoint).zigpy_endpoint = ep_mock

    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    cluster_handler_mock = mock.MagicMock(spec_set=ClusterHandler)
    with mock.patch(
        "zha.application.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        ENDPOINT_PROBE.probe_single_cluster(
            Platform.SWITCH, cluster_handler_mock, endpoint
        )

    assert get_entity_mock.call_count == 1
    assert endpoint.claim_cluster_handlers.call_count == 1
    assert endpoint.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
    assert endpoint.async_new_entity.call_count == 1
    assert endpoint.async_new_entity.call_args[0][0] == Platform.SWITCH
    assert endpoint.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls
    assert endpoint.async_new_entity.call_args[0][3] == mock.sentinel.claimed


@pytest.mark.parametrize("device_info", DEVICES)
async def test_discover_endpoint(
    device_info: dict[str, Any],
    zha_device_mock: Callable[..., Coroutine[Any, Any, Device]],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test device discovery."""

    with mock.patch("zha.zigbee.endpoint.Endpoint.async_new_entity") as new_ent:
        device = await zha_device_mock(
            device_info[SIG_ENDPOINTS],
            manufacturer=device_info[SIG_MANUFACTURER],
            model=device_info[SIG_MODEL],
            node_desc=zdo_t.NodeDescriptor(**device_info[SIG_NODE_DESC]),
            patch_cluster=True,
        )

    assert device_info[DEV_SIG_EVT_CLUSTER_HANDLERS] == sorted(
        ch.id
        for endpoint in device._endpoints.values()
        for ch in endpoint.client_cluster_handlers.values()
    )

    # build a dict of entity_class -> (platform, unique_id, cluster_handlers) tuple
    ha_ent_info = {}
    for call in new_ent.call_args_list:
        platform, entity_cls, unique_id, cluster_handlers = call[0]
        if not contains_ignored_suffix(unique_id):
            unique_id_head = UNIQUE_ID_HD.match(unique_id).group(
                0
            )  # ieee + endpoint_id
            ha_ent_info[(unique_id_head, entity_cls.__name__)] = (
                platform,
                unique_id,
                cluster_handlers,
            )

    for platform_id, ent_info in device_info[DEV_SIG_ENT_MAP].items():
        platform, unique_id = platform_id

        test_ent_class = ent_info[DEV_SIG_ENT_MAP_CLASS]
        test_unique_id_head = UNIQUE_ID_HD.match(unique_id).group(0)
        assert (test_unique_id_head, test_ent_class) in ha_ent_info

        entity_platform, entity_unique_id, entity_cluster_handlers = ha_ent_info[
            (test_unique_id_head, test_ent_class)
        ]
        assert platform is entity_platform.value
        # unique_id used for discover is the same for "multi entities"
        assert unique_id.startswith(entity_unique_id)
        assert {ch.name for ch in entity_cluster_handlers} == set(
            ent_info[DEV_SIG_CLUSTER_HANDLERS]
        )


def _ch_mock(cluster):
    """Return mock of a cluster_handler with a cluster."""
    cluster_handler = mock.MagicMock()
    type(cluster_handler).cluster = mock.PropertyMock(
        return_value=cluster(mock.MagicMock())
    )
    return cluster_handler


@mock.patch(
    (
        "zha.application.discovery.EndpointProbe"
        ".handle_on_off_output_cluster_exception"
    ),
    new=mock.MagicMock(),
)
@mock.patch("zha.application.discovery.EndpointProbe.probe_single_cluster")
def _test_single_input_cluster_device_class(probe_mock):
    """Test SINGLE_INPUT_CLUSTER_DEVICE_CLASS matching by cluster id or class."""

    door_ch = _ch_mock(zigpy.zcl.clusters.closures.DoorLock)
    cover_ch = _ch_mock(zigpy.zcl.clusters.closures.WindowCovering)
    multistate_ch = _ch_mock(zigpy.zcl.clusters.general.MultistateInput)

    class QuirkedIAS(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.security.IasZone):
        """Quirked IAS Zone cluster."""

    ias_ch = _ch_mock(QuirkedIAS)

    class _Analog(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.general.AnalogInput):
        pass

    analog_ch = _ch_mock(_Analog)

    endpoint = mock.MagicMock(spec_set=Endpoint)
    endpoint.unclaimed_cluster_handlers.return_value = [
        door_ch,
        cover_ch,
        multistate_ch,
        ias_ch,
    ]

    EndpointProbe().discover_by_cluster_id(endpoint)
    assert probe_mock.call_count == len(endpoint.unclaimed_cluster_handlers())
    probes = (
        (Platform.LOCK, door_ch),
        (Platform.COVER, cover_ch),
        (Platform.SENSOR, multistate_ch),
        (Platform.BINARY_SENSOR, ias_ch),
        (Platform.SENSOR, analog_ch),
    )
    for call, details in zip(probe_mock.call_args_list, probes):
        platform, ch = details
        assert call[0][0] == platform
        assert call[0][1] == ch


def test_single_input_cluster_device_class_by_cluster_class() -> None:
    """Test SINGLE_INPUT_CLUSTER_DEVICE_CLASS matching by cluster id or class."""
    mock_reg = {
        zigpy.zcl.clusters.closures.DoorLock.cluster_id: Platform.LOCK,
        zigpy.zcl.clusters.closures.WindowCovering.cluster_id: Platform.COVER,
        zigpy.zcl.clusters.general.AnalogInput: Platform.SENSOR,
        zigpy.zcl.clusters.general.MultistateInput: Platform.SENSOR,
        zigpy.zcl.clusters.security.IasZone: Platform.BINARY_SENSOR,
    }

    with mock.patch.dict(SINGLE_INPUT_CLUSTER_DEVICE_CLASS, mock_reg, clear=True):
        _test_single_input_cluster_device_class()


@pytest.mark.parametrize("override", [None, "switch"])
async def test_device_override(
    zha_gateway: Gateway, zigpy_device_mock, override
) -> None:
    """Test device discovery override."""

    zigpy_device = zigpy_device_mock(
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
        discovery.ENDPOINT_PROBE.initialize(zha_gateway)

    await zha_gateway.async_device_initialized(zigpy_device)
    await zha_gateway.async_block_till_done()
    zha_device = zha_gateway.get_device(zigpy_device.ieee)

    get_entity(zha_device, platform=Platform.SWITCH if override else Platform.LIGHT)


async def test_quirks_v2_entity_discovery(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
) -> None:
    """Test quirks v2 discovery."""

    zigpy_device = zigpy_device_mock(
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

    zha_device = await device_joined(zigpy_device)

    get_entity(zha_device, platform=Platform.NUMBER)


async def test_quirks_v2_entity_discovery_e1_curtain(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
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

    aqara_E1_device = zigpy_device_mock(
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

    zha_device = await device_joined(aqara_E1_device)

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
    zigpy_device_mock,
    manufacturer: str,
    model: str,
    augment_method: Callable[[QuirkBuilder], QuirkBuilder] | None = None,
):
    zigpy_device = zigpy_device_mock(
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
        )
        .sensor(
            zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            zigpy.zcl.clusters.general.OnOff.cluster_id,
            entity_type=EntityType.CONFIG,
            translation_key="analog_input",
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
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test quirks v2 discovery skipped - no metadata."""

    zigpy_device = _get_test_device(
        zigpy_device_mock, "Ikea of Sweden2", "TRADFRI remote control2"
    )
    setattr(zigpy_device, "_exposes_metadata", {})
    zha_device = await device_joined(zigpy_device)
    assert (
        f"Device: {str(zigpy_device.ieee)}-{zha_device.name} does not expose any quirks v2 entities"
        in caplog.text
    )


async def test_quirks_v2_entity_discovery_errors(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test quirks v2 discovery skipped - errors."""

    zigpy_device = _get_test_device(
        zigpy_device_mock, "Ikea of Sweden3", "TRADFRI remote control3"
    )
    zha_device = await device_joined(zigpy_device)

    m1 = f"Device: {str(zigpy_device.ieee)}-{zha_device.name} does not have an"
    m2 = " endpoint with id: 3 - unable to create entity with cluster"
    m3 = " details: (3, 6, <ClusterType.Server: 0>)"
    assert f"{m1}{m2}{m3}" in caplog.text

    time_cluster_id = zigpy.zcl.clusters.general.Time.cluster_id

    m1 = f"Device: {str(zigpy_device.ieee)}-{zha_device.name} does not have a"
    m2 = f" cluster with id: {time_cluster_id} - unable to create entity with "
    m3 = f"cluster details: (1, {time_cluster_id}, <ClusterType.Server: 0>)"
    assert f"{m1}{m2}{m3}" in caplog.text

    # fmt: off
    entity_details = (
        "{'cluster_details': (1, 6, <ClusterType.Server: 0>), 'entity_metadata': "
        "ZCLSensorMetadata(entity_platform=<EntityPlatform.SENSOR: 'sensor'>, "
        "entity_type=<EntityType.CONFIG: 'config'>, cluster_id=6, endpoint_id=1, "
        "cluster_type=<ClusterType.Server: 0>, initially_disabled=False, "
        "attribute_initialized_from_cache=True, translation_key='analog_input', "
        "fallback_name=None, attribute_name='off_wait_time', divisor=1, multiplier=1, "
        "unit=None, device_class=None, state_class=None)}"
    )
    # fmt: on

    m1 = f"Device: {str(zigpy_device.ieee)}-{zha_device.name} has an entity with "
    m2 = f"details: {entity_details} that does not have an entity class mapping - "
    m3 = "unable to create entity"
    assert f"{m1}{m2}{m3}" in caplog.text


DEVICE_CLASS_TYPES = [NumberMetadata, BinarySensorMetadata, ZCLSensorMetadata]


def validate_device_class_unit(
    quirk: QuirksV2RegistryEntry,
    entity_metadata: EntityMetadata,
    platform: Platform,
    translations: dict,  # pylint: disable=unused-argument
) -> None:
    """Ensure device class and unit are used correctly."""
    if (
        hasattr(entity_metadata, "unit")
        and entity_metadata.unit is not None
        and hasattr(entity_metadata, "device_class")
        and entity_metadata.device_class is not None
    ):
        m1 = "device_class and unit are both set - unit: "
        m2 = f"{entity_metadata.unit} device_class: "
        m3 = f"{entity_metadata.device_class} for {platform.name} "
        raise ValueError(f"{m1}{m2}{m3}{quirk}")


def validate_translation_keys(
    quirk: QuirksV2RegistryEntry,
    entity_metadata: EntityMetadata,
    platform: Platform,
    translations: dict,
) -> None:
    """Ensure translation keys exist for all v2 quirks."""
    if isinstance(entity_metadata, ZCLCommandButtonMetadata):
        default_translation_key = entity_metadata.command_name
    else:
        default_translation_key = entity_metadata.attribute_name
    translation_key = entity_metadata.translation_key or default_translation_key

    if (
        translation_key is not None
        and translation_key not in translations["entity"][platform]
    ):
        raise ValueError(
            f"Missing translation key: {translation_key} for {platform.name} {quirk}"
        )


def validate_translation_keys_device_class(
    quirk: QuirksV2RegistryEntry,
    entity_metadata: EntityMetadata,
    platform: Platform,
    translations: dict,  # pylint: disable=unused-argument
) -> None:
    """Validate translation keys and device class usage."""
    if isinstance(entity_metadata, ZCLCommandButtonMetadata):
        default_translation_key = entity_metadata.command_name
    else:
        default_translation_key = entity_metadata.attribute_name
    translation_key = entity_metadata.translation_key or default_translation_key

    metadata_type = type(entity_metadata)
    if metadata_type in DEVICE_CLASS_TYPES:
        device_class = entity_metadata.device_class
        if device_class is not None and translation_key is not None:
            m1 = "translation_key and device_class are both set - translation_key: "
            m2 = f"{translation_key} device_class: {device_class} for {platform.name} "
            raise ValueError(f"{m1}{m2}{quirk}")


def validate_metadata(validator: Callable) -> None:
    """Ensure v2 quirks metadata does not violate HA rules."""
    all_v2_quirks = itertools.chain.from_iterable(
        zigpy.quirks._DEVICE_REGISTRY._registry_v2.values()
    )
    translations: dict[str, dict[str, str]] = {}
    for quirk in all_v2_quirks:
        for entity_metadata in quirk.entity_metadata:
            platform = Platform(entity_metadata.entity_platform.value)
            validator(quirk, entity_metadata, platform, translations)


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
        device_class=BadDeviceClass.BAD,
    )


def bad_sensor_device_class(
    quirk_builder: QuirkBuilder,
) -> QuirkBuilder:
    """Introduce a bad device class on a sensor."""

    return quirk_builder.sensor(
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
        zigpy.zcl.clusters.general.OnOff.cluster_id,
        device_class=BadDeviceClass.BAD,
    )


def bad_number_device_class(
    quirk_builder: QuirkBuilder,
) -> QuirkBuilder:
    """Introduce a bad device class on a number."""

    return quirk_builder.number(
        zigpy.zcl.clusters.general.OnOff.AttributeDefs.on_time.name,
        zigpy.zcl.clusters.general.OnOff.cluster_id,
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
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
    augment_method: Callable[[QuirkBuilder], QuirkBuilder],
    expected_exception_string: str,
) -> None:
    """Test bad quirks v2 device classes."""

    # introduce an error
    zigpy_device = _get_test_device(
        zigpy_device_mock,
        "Ikea of Sweden5",
        "TRADFRI remote control5",
        augment_method=augment_method,
    )
    await device_joined(zigpy_device)

    assert expected_exception_string in caplog.text

    # remove the device so we don't pollute the rest of the tests
    zigpy.quirks._DEVICE_REGISTRY.remove(zigpy_device)


async def test_quirks_v2_fallback_name(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    zigpy_device_mock,
    device_joined: Callable[[zigpy.device.Device], Awaitable[Device]],
) -> None:
    """Test quirks v2 fallback name."""

    zigpy_device = _get_test_device(
        zigpy_device_mock,
        "Ikea of Sweden6",
        "TRADFRI remote control6",
        augment_method=lambda builder: builder.sensor(
            attribute_name=zigpy.zcl.clusters.general.OnOff.AttributeDefs.off_wait_time.name,
            cluster_id=zigpy.zcl.clusters.general.OnOff.cluster_id,
            translation_key="some_sensor",
            fallback_name="Fallback name",
        ),
    )
    zha_device = await device_joined(zigpy_device)

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
    zha_device_from_file: Callable[..., Awaitable[Device]], file_path: str
) -> None:
    """Test all devices."""
    with mock.patch(
        "zigpy.zcl.clusters.general.Identify.request",
        new=AsyncMock(return_value=[mock.sentinel.data, zcl_f.Status.SUCCESS]),
    ):
        zha_device = await zha_device_from_file(file_path)
        assert zha_device is not None

        device_data = json.loads(
            await asyncio.get_running_loop().run_in_executor(None, file_path.read_text)
        )

        # Get the zha_lib_entities from device_data
        zha_lib_entities = device_data.get("zha_lib_entities", [])

        entity_count = 0
        # Iterate over the platform_entities in device.platform_entities
        for platform, entities in zha_lib_entities.items():
            for entity in entities:
                entity_count += 1
                platform_entity = zha_device.platform_entities.get(
                    (Platform(platform), entity["info_object"]["unique_id"])
                )
                assert platform_entity is not None

                # Assert that the entity properties match those in the json data
                assert (
                    platform_entity.translation_key
                    == entity["info_object"]["translation_key"]
                )
                assert (
                    platform_entity.fallback_name
                    == entity["info_object"]["fallback_name"]
                )
                assert (
                    platform_entity.device_class
                    == entity["info_object"]["device_class"]
                )
                assert (
                    platform_entity.__class__.__name__ == entity["state"]["class_name"]
                )
                assert (
                    platform_entity.entity_category
                    == entity["info_object"]["entity_category"]
                )
                assert (
                    platform_entity.state_class == entity["info_object"]["state_class"]
                )
                assert (
                    platform_entity.entity_registry_enabled_default
                    == entity["info_object"]["entity_registry_enabled_default"]
                )
                assert (
                    platform_entity.state["class_name"] == entity["state"]["class_name"]
                )

        # Assert that the number of entities in the device matches the number of entities in the json data
        assert len(zha_device.platform_entities) == entity_count

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
