"""Test zha siren."""

import asyncio
from unittest.mock import call, patch

from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
from zigpy.quirks import DEVICE_REGISTRY
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
from zigpy.quirks.v2.homeassistant import EntityPlatform
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    mock_coro,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.siren import (
    ConfigurableAttributeSiren,
    EnumSiren,
    SirenEntityFeature,
)
from zha.zigbee.device import Device


async def siren_mock(
    zha_gateway: Gateway,
    basic: bool = False,
) -> tuple[Device, security.IasWd]:
    """Siren fixture."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    if basic:
        zigpy_device.quirk_id = {"siren_basic"}

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd


async def test_siren(zha_gateway: Gateway) -> None:
    """Test zha siren platform."""

    zha_device, cluster = await siren_mock(zha_gateway)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.TONES
        | SirenEntityFeature.VOLUME_SET
        | SirenEntityFeature.DURATION
    )

    assert entity.state["state"] is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 2  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state["state"] is False

    # turn on from client with options
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on(duration=100, volume_level=3, tone=3)
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 51  # bitmask for specified args
        assert cluster.request.call_args[0][4] == 100  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True


async def test_basic_siren(zha_gateway: Gateway) -> None:
    """Test zha basic siren."""

    zha_device, cluster = await siren_mock(zha_gateway, basic=True)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.DURATION
    )

    assert entity.state["state"] is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 2  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state["state"] is False

    # turn on from client with duration option
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on(duration=100)
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for specified args
        assert cluster.request.call_args[0][4] == 100  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True


async def test_siren_timed_off(zha_gateway: Gateway) -> None:
    """Test zha siren platform."""
    zha_device, cluster = await siren_mock(zha_gateway)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)

    assert entity.state["state"] is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    await asyncio.sleep(6)

    # test that the state has changed to off from the timer
    assert entity.state["state"] is False


async def test_siren_configurable_attribute(zha_gateway: Gateway) -> None:
    """Test ZHA configurable attribute siren created from quirks v2 SwitchMetadata."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="FakeSirenManufacturer",
        model="FakeSirenModel",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .switch(
            general.Basic.AttributeDefs.power_source.name,
            general.Basic.cluster_id,
            on_value=1,
            off_value=0,
            entity_platform=EntityPlatform.SIREN,
            translation_key="siren",
            fallback_name="Siren",
        )
        .add_to_registry()
    )

    zigpy_device_ = DEVICE_REGISTRY.get_device(zigpy_dev)
    assert isinstance(zigpy_device_, CustomDeviceV2)

    cluster = zigpy_device_.endpoints[1].basic
    cluster.PLUGGED_ATTR_READS = {
        general.Basic.AttributeDefs.power_source.name: 0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert isinstance(entity, ConfigurableAttributeSiren)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF
    )
    assert entity.state["state"] is False

    # turn on via attribute report
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 1}
    )
    assert entity.state["state"] is True

    # turn off via attribute report
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 0}
    )
    assert entity.state["state"] is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 1},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 0},
                manufacturer=UNDEFINED,
            )
        ]


async def test_siren_configurable_attribute_custom_on_off_values(
    zha_gateway: Gateway,
) -> None:
    """Test configurable attribute siren with custom on/off values."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="FakeSirenManufacturer2",
        model="FakeSirenModel2",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .switch(
            general.Basic.AttributeDefs.power_source.name,
            general.Basic.cluster_id,
            on_value=3,
            off_value=5,
            entity_platform=EntityPlatform.SIREN,
            translation_key="siren",
            fallback_name="Siren",
        )
        .add_to_registry()
    )

    zigpy_device_ = DEVICE_REGISTRY.get_device(zigpy_dev)
    assert isinstance(zigpy_device_, CustomDeviceV2)

    cluster = zigpy_device_.endpoints[1].basic
    cluster.PLUGGED_ATTR_READS = {
        general.Basic.AttributeDefs.power_source.name: 5,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)
    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert isinstance(entity, ConfigurableAttributeSiren)
    assert entity.state["state"] is False

    # turn on via attribute report
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 3}
    )
    assert entity.state["state"] is True

    # turn off via attribute report
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 5}
    )
    assert entity.state["state"] is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 3},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 5},
                manufacturer=UNDEFINED,
            )
        ]


async def test_siren_configurable_attribute_force_inverted(
    zha_gateway: Gateway,
) -> None:
    """Test configurable attribute siren with force_inverted=True."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="FakeSirenManufacturer3",
        model="FakeSirenModel3",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .switch(
            general.Basic.AttributeDefs.power_source.name,
            general.Basic.cluster_id,
            on_value=3,
            off_value=5,
            force_inverted=True,
            entity_platform=EntityPlatform.SIREN,
            translation_key="siren",
            fallback_name="Siren",
        )
        .add_to_registry()
    )

    zigpy_device_ = DEVICE_REGISTRY.get_device(zigpy_dev)
    assert isinstance(zigpy_device_, CustomDeviceV2)

    cluster = zigpy_device_.endpoints[1].basic
    cluster.PLUGGED_ATTR_READS = {
        general.Basic.AttributeDefs.power_source.name: 5,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)
    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert isinstance(entity, ConfigurableAttributeSiren)

    # with force_inverted, off_value=5 reads as on
    assert entity.state["state"] is True

    # attribute = on_value(3) -> inverted -> state is off
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 3}
    )
    assert entity.state["state"] is False

    # attribute = off_value(5) -> inverted -> state is on
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 5}
    )
    assert entity.state["state"] is True

    # turn on from HA: inverted, so writes off_value
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 5},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA: inverted, so writes on_value
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 3},
                manufacturer=UNDEFINED,
            )
        ]


async def test_siren_configurable_attribute_inverter_attribute(
    zha_gateway: Gateway,
) -> None:
    """Test configurable attribute siren with invert_attribute_name."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="FakeSirenManufacturer4",
        model="FakeSirenModel4",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .switch(
            general.Basic.AttributeDefs.power_source.name,
            general.Basic.cluster_id,
            on_value=3,
            off_value=5,
            invert_attribute_name=general.Basic.AttributeDefs.disable_local_config.name,
            entity_platform=EntityPlatform.SIREN,
            translation_key="siren",
            fallback_name="Siren",
        )
        .add_to_registry()
    )

    zigpy_device_ = DEVICE_REGISTRY.get_device(zigpy_dev)
    assert isinstance(zigpy_device_, CustomDeviceV2)

    cluster = zigpy_device_.endpoints[1].basic
    cluster.PLUGGED_ATTR_READS = {
        general.Basic.AttributeDefs.power_source.name: 5,
        general.Basic.AttributeDefs.disable_local_config.name: t.Bool(True),
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)
    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert isinstance(entity, ConfigurableAttributeSiren)

    # inverter_attribute is True, so off_value(5) reads as on
    assert entity.state["state"] is True

    # attribute = on_value(3), inverter still True -> state is off
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 3}
    )
    assert entity.state["state"] is False

    # inverter attribute flipped to False -> off_value(5) with no inversion -> off
    await send_attributes_report(
        zha_gateway,
        cluster,
        {general.Basic.AttributeDefs.disable_local_config.name: t.Bool(False)},
    )
    await send_attributes_report(
        zha_gateway, cluster, {general.Basic.AttributeDefs.power_source.name: 5}
    )
    assert entity.state["state"] is False

    # turn on from HA (not inverted now): writes on_value
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 3},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA: writes off_value
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {general.Basic.AttributeDefs.power_source.name: 5},
                manufacturer=UNDEFINED,
            )
        ]


async def test_siren_enum(zha_gateway: Gateway) -> None:
    """Test ZHA enum siren created from quirks v2 ZCLEnumMetadata.

    Uses a custom enum whose entries map to siren alert modes:
    - entry 0 (Off)    → off state
    - entry 1 (Alert)  → default on tone
    - entry 2 (Alarm)  → named tone
    """

    class SirenMode(t.enum8):
        Off = 0x00
        Tone_1 = 0x01
        Tone_2 = 0x02

    attr_name = general.Basic.AttributeDefs.disable_local_config.name

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="FakeSirenManufacturer5",
        model="FakeSirenModel5",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .enum(
            attr_name,
            SirenMode,
            general.Basic.cluster_id,
            entity_platform=EntityPlatform.SIREN,
            translation_key="siren_mode",
            fallback_name="Siren mode",
        )
        .add_to_registry()
    )

    zigpy_device_ = DEVICE_REGISTRY.get_device(zigpy_dev)
    assert isinstance(zigpy_device_, CustomDeviceV2)

    cluster = zigpy_device_.endpoints[1].basic
    cluster.PLUGGED_ATTR_READS = {attr_name: SirenMode.Off}
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)
    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert isinstance(entity, EnumSiren)

    # Entry 0 (Off) = off state; entries 1+ are available tones
    assert entity.available_tones == {
        SirenMode.Tone_1.value: "Tone 1",
        SirenMode.Tone_2.value: "Tone 2",
    }
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.TONES
    )

    # Initial state: Off (0) -> off
    assert entity.state["state"] is False

    # Attribute report: Alert -> on
    await send_attributes_report(zha_gateway, cluster, {attr_name: SirenMode.Tone_1})
    assert entity.state["state"] is True

    # Attribute report: Off -> off
    await send_attributes_report(zha_gateway, cluster, {attr_name: SirenMode.Off})
    assert entity.state["state"] is False

    # Turn on without tone: writes entry 1 (Alert)
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({attr_name: SirenMode.Tone_1}, manufacturer=UNDEFINED)
        ]
        cluster.write_attributes.reset_mock()

    # Turn on with a specific tone (Alarm = value 2)
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on(tone=SirenMode.Tone_2.value)
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({attr_name: SirenMode.Tone_2}, manufacturer=UNDEFINED)
        ]
        cluster.write_attributes.reset_mock()

    # Turn off: writes entry 0 (Off)
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({attr_name: SirenMode.Off}, manufacturer=UNDEFINED)
        ]
