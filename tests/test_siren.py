"""Test zha siren."""

import asyncio
from unittest.mock import call, patch

from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

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
from zha.application.platforms.siren import AttributeSiren, SirenEntityFeature
from zha.quirks import QUIRK_REGISTRY_ENTRY_ATTR, SIREN_BASIC, DeviceRegistry
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
        zigpy_device.quirk_id = {SIREN_BASIC}

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 50  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 2  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 51  # bitmask for specified args
        assert kw["warning_duration"] == 100  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 18  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 2  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 18  # bitmask for specified args
        assert kw["warning_duration"] == 100  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 50  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["stobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    await asyncio.sleep(6)

    # test that the state has changed to off from the timer
    assert entity.state["state"] is False


class _SmokeSirenEnum(t.enum8):
    """Smoke siren type."""

    Stop = 0
    Smoke_siren = 1
    CO_siren = 2


class _SirenManufCluster(CustomCluster):
    """Manufacturer-specific cluster with the attribute-controlled siren."""

    cluster_id = 0xFC90
    ep_attribute = "heiman_siren"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        siren_for_automation = ZCLAttributeDef(
            id=0x0012, type=_SmokeSirenEnum, manufacturer_code=0x120B
        )


async def attribute_siren_mock(
    zha_gateway: Gateway,
) -> tuple[Device, security.IasWd, CustomCluster]:
    """Build a device whose quirk replaces the IAS WD siren with an AttributeSiren."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    security.IasWd.cluster_id,
                    _SirenManufCluster.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_ZONE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="HEIMAN",
        model="attribute-siren-test",
    )

    registry = DeviceRegistry()
    (
        QuirkBuilder(zigpy_device.manufacturer, zigpy_device.model)
        .replaces(_SirenManufCluster)
        .prevent_default_entity_creation(
            endpoint_id=1, cluster_id=security.IasWd.cluster_id
        )
        .siren(
            _SirenManufCluster.AttributeDefs.siren_for_automation.name,
            _SirenManufCluster.cluster_id,
            available_tones={
                _SmokeSirenEnum.Smoke_siren: "Smoke siren",
                _SmokeSirenEnum.CO_siren: "CO siren",
            },
            off_value=_SmokeSirenEnum.Stop,
            default_tone=_SmokeSirenEnum.Smoke_siren,
            unique_id_suffix=str(security.IasWd.cluster_id),
            translation_key="siren",
            fallback_name="Siren",
        )
        .add_to_registry(registry)
    )

    zigpy_device = registry.resolve(zigpy_device)
    assert getattr(zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR, None) is not None

    cluster = zigpy_device.endpoints[1].heiman_siren
    cluster.PLUGGED_ATTR_READS = {"siren_for_automation": _SmokeSirenEnum.Stop}
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd, cluster


async def test_attribute_siren(zha_gateway: Gateway) -> None:
    """Test the quirks v2 attribute-controlled siren entity."""
    zha_device, ias_wd, cluster = await attribute_siren_mock(zha_gateway)

    entity = get_entity(zha_device, platform=Platform.SIREN)

    # the IAS WD siren was suppressed and replaced by the AttributeSiren, which
    # reuses the IAS WD siren's unique_id so existing entities migrate
    assert isinstance(entity, AttributeSiren)
    assert entity.unique_id.endswith(f"-1-{int(security.IasWd.cluster_id)}")

    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.TONES
    )
    assert entity.available_tones == {
        _SmokeSirenEnum.Smoke_siren: "Smoke siren",
        _SmokeSirenEnum.CO_siren: "CO siren",
    }

    # seeded to Stop
    assert entity.state["state"] is False

    # device-driven report turns the siren on...
    await send_attributes_report(
        zha_gateway, cluster, {"siren_for_automation": _SmokeSirenEnum.Smoke_siren}
    )
    assert entity.state["state"] is True

    # ...and the device's own reset back to Stop (e.g. the ~10 min timeout)
    # updates the entity state without any user action
    await send_attributes_report(
        zha_gateway, cluster, {"siren_for_automation": _SmokeSirenEnum.Stop}
    )
    assert entity.state["state"] is False

    # turn on from HA without a tone writes the default tone
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {"siren_for_automation": _SmokeSirenEnum.Smoke_siren},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn on with an explicit tone writes that tone
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_on(tone=_SmokeSirenEnum.CO_siren)
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call(
                {"siren_for_automation": _SmokeSirenEnum.CO_siren},
                manufacturer=UNDEFINED,
            )
        ]
        cluster.write_attributes.reset_mock()

    # turn off writes the off value
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"siren_for_automation": _SmokeSirenEnum.Stop}, manufacturer=UNDEFINED)
        ]
