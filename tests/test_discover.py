"""Test zha device discovery."""

import itertools
import re
from typing import Awaitable, Callable
from unittest import mock

import pytest
from slugify import slugify
from zigpy.const import SIG_ENDPOINTS, SIG_MANUFACTURER, SIG_MODEL, SIG_NODE_DESC
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
import zigpy.quirks
import zigpy.types
import zigpy.zcl.clusters.closures
import zigpy.zcl.clusters.general as general
import zigpy.zcl.clusters.security

from zhaws.client.controller import Controller
import zhaws.server.platforms.discovery as disc
from zhaws.server.platforms.registries import (
    PLATFORM_ENTITIES,
    SINGLE_INPUT_CLUSTER_DEVICE_CLASS,
    Platform,
)
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.cluster import ClusterHandler
from zhaws.server.zigbee.device import Device
from zhaws.server.zigbee.endpoint import Endpoint

from .zha_devices_list import (
    DEV_SIG_CHANNELS,
    DEV_SIG_ENT_MAP,
    DEV_SIG_ENT_MAP_CLASS,
    DEV_SIG_ENT_MAP_ID,
    DEV_SIG_EVT_CHANNELS,
    DEV_SIG_ZHA_QUIRK,
    DEVICES,
)

NO_TAIL_ID = re.compile("_\\d$")
UNIQUE_ID_HD = re.compile(r"^(([\da-fA-F]{2}:){7}[\da-fA-F]{2}-\d{1,3})", re.X)


@pytest.fixture
def zhaws_device_mock(
    zigpy_device_mock: Callable[..., zigpy.device.Device],
    device_joined: Callable[..., Device],
) -> Callable[..., Device]:
    """Channels mock factory."""

    async def _mock(
        endpoints,
        ieee="00:11:22:33:44:55:66:77",
        manufacturer="mock manufacturer",
        model="mock model",
        node_desc=b"\x02@\x807\x10\x7fd\x00\x00*d\x00\x00",
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


"""
@patch(
    "zigpy.zcl.clusters.general.Identify.request",
    new=AsyncMock(return_value=[mock.sentinel.data, zcl_f.Status.SUCCESS]),
)
"""


@pytest.mark.parametrize("device", DEVICES)
async def test_devices(
    device: dict,
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test device discovery."""
    controller, server = connected_client_and_server
    zigpy_device = zigpy_device_mock(
        device[SIG_ENDPOINTS],
        "00:11:22:33:44:55:66:77",
        device[SIG_MANUFACTURER],
        device[SIG_MODEL],
        node_descriptor=device[SIG_NODE_DESC],
        quirk=device[DEV_SIG_ZHA_QUIRK] if DEV_SIG_ZHA_QUIRK in device else None,
        patch_cluster=True,
    )

    """
    cluster_identify = _get_first_identify_cluster(zigpy_device)
    if cluster_identify:
        cluster_identify.request.reset_mock()
    """

    server.controller.application_controller.get_device(
        nwk=0x0000
    ).add_to_group = mock.AsyncMock(return_value=[0])
    orig_new_entity = Endpoint.async_new_entity
    _dispatch = mock.MagicMock(wraps=orig_new_entity)
    try:
        Endpoint.async_new_entity = lambda *a, **kw: _dispatch(*a, **kw)  # type: ignore
        zha_dev = await device_joined(zigpy_device)
        await server.block_till_done()
    finally:
        Endpoint.async_new_entity = orig_new_entity  # type: ignore

    """
    if cluster_identify:
        assert cluster_identify.request.call_count is True
        assert cluster_identify.request.await_count is True
        assert cluster_identify.request.call_args == mock.call(
            False,
            64,
            cluster_identify.commands_by_name["trigger_effect"].schema,
            2,
            0,
            expect_reply=True,
            manufacturer=None,
            tries=1,
            tsn=None,
        )
    """

    event_channels = {
        ch.id
        for endpoint in zha_dev._endpoints.values()
        for ch in endpoint.client_cluster_handlers.values()
    }
    assert event_channels == set(device[DEV_SIG_EVT_CHANNELS])
    # we need to probe the class create entity factory so we need to reset this to get accurate results
    PLATFORM_ENTITIES.clean_up()
    # build a dict of entity_class -> (platform, unique_id, channels) tuple
    ha_ent_info = {}
    created_entity_count = 0
    for call in _dispatch.call_args_list:
        _, platform, entity_cls, unique_id, channels = call[0]
        # the factory can return None. We filter these out to get an accurate created entity count
        response = entity_cls.create_platform_entity(
            unique_id, channels, channels[0]._endpoint, zha_dev
        )
        if response:
            await response.on_remove()
            created_entity_count += 1
            unique_id_head = UNIQUE_ID_HD.match(unique_id).group(
                0
            )  # ieee + endpoint_id
            ha_ent_info[(unique_id_head, entity_cls.__name__)] = (
                platform,
                unique_id,
                channels,
            )

    for comp_id, ent_info in device[DEV_SIG_ENT_MAP].items():
        platform, unique_id = comp_id
        test_ent_class = ent_info[DEV_SIG_ENT_MAP_CLASS]
        test_unique_id_head = UNIQUE_ID_HD.match(unique_id).group(0)
        assert (test_unique_id_head, test_ent_class) in ha_ent_info

        ha_comp, ha_unique_id, ha_channels = ha_ent_info[
            (test_unique_id_head, test_ent_class)
        ]
        assert platform is ha_comp.value
        # unique_id used for discover is the same for "multi entities"
        assert unique_id.startswith(ha_unique_id)
        assert {ch.name for ch in ha_channels} == set(ent_info[DEV_SIG_CHANNELS])

    assert created_entity_count == len(device[DEV_SIG_ENT_MAP])

    zha_entity_ids = [
        entity.PLATFORM + "." + slugify(entity.name, separator="_")
        for entity in zha_dev.platform_entities.values()
    ]
    grouped_entity_ids = itertools.groupby(zha_entity_ids, lambda x: x.split(".")[0])
    ent_set = set()
    for platform, entities in grouped_entity_ids:
        # HA does this for us when hinting entity id off of name
        count = 2
        for ent_id in entities:
            if ent_id in ent_set:
                ent_set.add(f"{ent_id}_{count}")
                count += 1
            else:
                ent_set.add(ent_id)

    assert ent_set == {e[DEV_SIG_ENT_MAP_ID] for e in device[DEV_SIG_ENT_MAP].values()}


def _get_first_identify_cluster(zigpy_device: ZigpyDevice) -> general.Identify:
    for endpoint in list(zigpy_device.endpoints.values())[1:]:
        if hasattr(endpoint, "identify"):
            return endpoint.identify


@mock.patch("zhaws.server.platforms.discovery.ProbeEndpoint.discover_by_device_type")
@mock.patch("zhaws.server.platforms.discovery.ProbeEndpoint.discover_by_cluster_id")
def test_discover_entities(m1, m2):
    """Test discover endpoint class method."""
    ep_channels = mock.MagicMock()
    disc.PROBE.discover_entities(ep_channels)
    assert m1.call_count == 1
    assert m1.call_args[0][0] is ep_channels
    assert m2.call_count == 1
    assert m2.call_args[0][0] is ep_channels


@pytest.mark.parametrize(
    "device_type, platform, hit",
    [
        (zigpy.profiles.zha.DeviceType.ON_OFF_LIGHT, Platform.LIGHT, True),
        (zigpy.profiles.zha.DeviceType.ON_OFF_BALLAST, Platform.SWITCH, True),
        (zigpy.profiles.zha.DeviceType.SMART_PLUG, Platform.SWITCH, True),
        (0xFFFF, None, False),
    ],
)
def test_discover_by_device_type(device_type, platform, hit) -> None:
    """Test entity discovery by device type."""

    ep_channels = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = device_type
    type(ep_channels).zigpy_endpoint = ep_mock

    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    with mock.patch(
        "zhaws.server.platforms.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        disc.PROBE.discover_by_device_type(ep_channels)
    if hit:
        assert get_entity_mock.call_count == 1
        assert ep_channels.claim_cluster_handlers.call_count == 1
        assert (
            ep_channels.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
        )
        assert ep_channels.async_new_entity.call_count == 1
        assert ep_channels.async_new_entity.call_args[0][0] == platform
        assert ep_channels.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls


""" TODO uncomment when overrides are supported again
def test_discover_by_device_type_override() -> None:
    # Test entity discovery by device type overriding.

    ep_channels = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = 0x0100
    type(ep_channels).zigpy_endpoint = ep_mock

    overrides = {ep_channels.unique_id: {"type": Platform.SWITCH}}
    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    with mock.patch(
        "zhaws.server.platforms.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ), mock.patch.dict(disc.PROBE._device_configs, overrides, clear=True):
        disc.PROBE.discover_by_device_type(ep_channels)
        assert get_entity_mock.call_count == 1
        assert ep_channels.claim_cluster_handlers.call_count == 1
        assert (
            ep_channels.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
        )
        assert ep_channels.async_new_entity.call_count == 1
        assert ep_channels.async_new_entity.call_args[0][0] == Platform.SWITCH
        assert ep_channels.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls
"""


def test_discover_probe_single_cluster() -> None:
    """Test entity discovery by single cluster."""

    ep_channels = mock.MagicMock(spec_set=Endpoint)
    ep_mock = mock.PropertyMock()
    ep_mock.return_value.profile_id = 0x0104
    ep_mock.return_value.device_type = 0x0100
    type(ep_channels).zigpy_endpoint = ep_mock

    get_entity_mock = mock.MagicMock(
        return_value=(mock.sentinel.entity_cls, mock.sentinel.claimed)
    )
    cluster_handler_mock = mock.MagicMock(spec_set=ClusterHandler)
    with mock.patch(
        "zhaws.server.platforms.registries.PLATFORM_ENTITIES.get_entity",
        get_entity_mock,
    ):
        disc.PROBE.probe_single_cluster(
            Platform.SWITCH, cluster_handler_mock, ep_channels
        )

    assert get_entity_mock.call_count == 1
    assert ep_channels.claim_cluster_handlers.call_count == 1
    assert ep_channels.claim_cluster_handlers.call_args[0][0] is mock.sentinel.claimed
    assert ep_channels.async_new_entity.call_count == 1
    assert ep_channels.async_new_entity.call_args[0][0] == Platform.SWITCH
    assert ep_channels.async_new_entity.call_args[0][1] == mock.sentinel.entity_cls
    assert ep_channels.async_new_entity.call_args[0][3] == mock.sentinel.claimed


@pytest.mark.parametrize("device_info", DEVICES)
async def test_discover_endpoint(
    device_info: dict,
    zhaws_device_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test device discovery."""
    controller, server = connected_client_and_server
    server.controller.application_controller.get_device(
        nwk=0x0000
    ).add_to_group = mock.AsyncMock(return_value=[0])
    with mock.patch(
        "zhaws.server.zigbee.endpoint.Endpoint.async_new_entity"
    ) as new_ent:
        device: Device = await zhaws_device_mock(
            device_info[SIG_ENDPOINTS],
            manufacturer=device_info[SIG_MANUFACTURER],
            model=device_info[SIG_MODEL],
            node_desc=device_info[SIG_NODE_DESC],
            patch_cluster=True,
        )

    assert device_info[DEV_SIG_EVT_CHANNELS] == sorted(
        ch.id
        for endpoint in device._endpoints.values()
        for ch in endpoint.client_cluster_handlers.values()
    )

    # build a dict of entity_class -> (platform, unique_id, cluster_handlers) tuple
    entity_info = {}
    for call in new_ent.call_args_list:
        platform, entity_cls, unique_id, cluster_handlers = call[0]
        unique_id_head = UNIQUE_ID_HD.match(unique_id).group(0)  # ieee + endpoint_id
        entity_info[(unique_id_head, entity_cls.__name__)] = (
            platform,
            unique_id,
            cluster_handlers,
        )

    for platform_id, ent_info in device_info[DEV_SIG_ENT_MAP].items():
        platform, unique_id = platform_id

        test_ent_class = ent_info[DEV_SIG_ENT_MAP_CLASS]
        test_unique_id_head = UNIQUE_ID_HD.match(unique_id).group(0)
        assert (test_unique_id_head, test_ent_class) in entity_info

        entity_platform, entity_unique_id, entity_cluster_handlers = entity_info[
            (test_unique_id_head, test_ent_class)
        ]
        assert platform is entity_platform.value
        # unique_id used for discover is the same for "multi entities"
        assert unique_id.startswith(entity_unique_id)
        assert {ch.name for ch in entity_cluster_handlers} == set(
            ent_info[DEV_SIG_CHANNELS]
        )


def _ch_mock(cluster):
    """Return mock of a channel with a cluster."""
    channel = mock.MagicMock()
    type(channel).cluster = mock.PropertyMock(return_value=cluster(mock.MagicMock()))
    return channel


@mock.patch(
    "zhaws.server.platforms.discovery.ProbeEndpoint"
    ".handle_on_off_output_cluster_exception",
    new=mock.MagicMock(),
)
@mock.patch("zhaws.server.platforms.discovery.ProbeEndpoint.probe_single_cluster")
def _test_single_input_cluster_device_class(probe_mock):
    """Test SINGLE_INPUT_CLUSTER_DEVICE_CLASS matching by cluster id or class."""

    door_ch = _ch_mock(zigpy.zcl.clusters.closures.DoorLock)
    cover_ch = _ch_mock(zigpy.zcl.clusters.closures.WindowCovering)
    multistate_ch = _ch_mock(zigpy.zcl.clusters.general.MultistateInput)

    class QuirkedIAS(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.security.IasZone):
        pass

    ias_ch = _ch_mock(QuirkedIAS)

    class _Analog(zigpy.quirks.CustomCluster, zigpy.zcl.clusters.general.AnalogInput):
        pass

    analog_ch = _ch_mock(_Analog)

    ch_pool = mock.MagicMock(spec_set=Endpoint)
    ch_pool.unclaimed_cluster_handlers.return_value = [
        door_ch,
        cover_ch,
        multistate_ch,
        ias_ch,
    ]

    disc.ProbeEndpoint().discover_by_cluster_id(ch_pool)
    assert probe_mock.call_count == len(ch_pool.unclaimed_cluster_handlers())
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


"""
@pytest.mark.parametrize(
    "override, entity_id",
    [
        (None, "light.manufacturer_model_77665544_level_light_color_on_off"),
        ("switch", "switch.manufacturer_model_77665544_on_off"),
    ],
)
async def test_device_override(
    zigpy_device_mock, setup_zha, override, entity_id
):
    #Test device discovery override.

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
        override = {"device_config": {"00:11:22:33:44:55:66:77-1": {"type": override}}}

    await setup_zha(override)
    assert hass_disable_services.states.get(entity_id) is None
    zha_gateway = get_zha_gateway(hass_disable_services)
    await zha_gateway.async_device_initialized(zigpy_device)
    await hass_disable_services.async_block_till_done()
    assert hass_disable_services.states.get(entity_id) is not None
"""

"""
async def test_group_probe_cleanup_called(setup_zha, config_entry):
    # Test cleanup happens when zha is unloaded.
    await setup_zha()
    disc.GROUP_PROBE.cleanup = mock.Mock(wraps=disc.GROUP_PROBE.cleanup)
    await config_entry.async_unload(hass_disable_services)
    await hass_disable_services.async_block_till_done()
    disc.GROUP_PROBE.cleanup.assert_called()
"""
