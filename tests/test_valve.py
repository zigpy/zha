"""Test zha valve."""

from unittest.mock import AsyncMock, call, patch

import pytest
import zigpy.zcl.foundation as zcl_f

from tests.common import get_entity, join_zigpy_device, zigpy_device_from_json
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.helpers import DeviceOverridesConfiguration
from zha.application.platforms.valve import Valve
from zha.application.platforms.valve.const import ValveEntityFeature


async def test_valve_not_discovered_by_default(zha_gateway: Gateway) -> None:
    """Test that valves are not discovered by default."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-swv.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    with pytest.raises(KeyError):
        get_entity(zha_device, platform=Platform.VALVE)

    get_entity(
        zha_device,
        platform=Platform.SWITCH,
        qualifier_func=lambda entity: (
            entity.cluster_handlers.get("on_off")
            and entity.cluster_handlers["on_off"].cluster
            == zigpy_device.endpoints[1].on_off
        ),
    )


async def test_valve_discovered_via_platform_override(zha_gateway: Gateway) -> None:
    """Test valve discovery when overridden via device configuration."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-swv.json",
    )

    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-1": DeviceOverridesConfiguration(type=Platform.VALVE)
    }

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    valve = get_entity(
        zha_device,
        platform=Platform.VALVE,
        exact_entity_type=Valve,
        qualifier_func=lambda entity: (
            entity.cluster_handlers.get("on_off")
            and entity.cluster_handlers["on_off"].cluster
            == zigpy_device.endpoints[1].on_off
        ),
    )

    assert valve.supported_features == (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )
    assert valve.reports_position is False

    with pytest.raises(KeyError):
        get_entity(
            zha_device,
            platform=Platform.SWITCH,
            qualifier_func=lambda entity: (
                entity.cluster_handlers.get("on_off")
                and entity.cluster_handlers["on_off"].cluster
                == zigpy_device.endpoints[1].on_off
            ),
        )


async def test_valve_level_control_commands(zha_gateway: Gateway) -> None:
    """Test level-based valve set_position and stop with platform override."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sinope-technologies-va4220zb.json",
    )

    zha_gateway.config.config.device_overrides = {
        f"{zigpy_device.ieee}-1": DeviceOverridesConfiguration(type=Platform.VALVE)
    }

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    valve = get_entity(
        zha_device,
        platform=Platform.VALVE,
        exact_entity_type=Valve,
        qualifier_func=lambda entity: (
            entity.cluster_handlers.get("on_off")
            and entity.cluster_handlers["on_off"].cluster
            == zigpy_device.endpoints[1].on_off
        ),
    )

    assert valve.reports_position is True
    assert valve.supported_features & ValveEntityFeature.SET_POSITION
    assert valve.supported_features & ValveEntityFeature.STOP

    level_cluster = zigpy_device.endpoints[1].level

    with patch.object(
        level_cluster,
        "move_to_level_with_on_off",
        AsyncMock(return_value=[0, zcl_f.Status.SUCCESS]),
    ) as move_to_level_with_on_off:
        await valve.async_set_valve_position(position=47)
        await zha_gateway.async_block_till_done()
        assert move_to_level_with_on_off.mock_calls == [call(120, 1)]

    with patch.object(
        level_cluster, "stop", AsyncMock(return_value=[0, zcl_f.Status.SUCCESS])
    ) as stop:
        await valve.async_stop_valve()
        await zha_gateway.async_block_till_done()
        assert stop.mock_calls == [call()]
