"""Test coordinator LED light support."""

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bellows.ezsp.xncp import FirmwareFeatures
import pytest

from tests.common import get_entity
import tests.conftest as test_conftest
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.light import (
    DEFAULT_COORDINATOR_LED_BRIGHTNESS,
    DEFAULT_COORDINATOR_LED_XY_COLOR,
    CoordinatorLED,
    _xy_brightness_to_rgb,
)
from zha.application.platforms.light.const import ColorMode


@pytest.fixture
async def zbt2_gateway(
    zha_data,
    zigpy_app_controller,
    caplog,  # pylint: disable=unused-argument
) -> AsyncGenerator[Gateway, None]:
    """Set up a ZBT-2-capable gateway."""
    zigpy_app_controller.state.node_info.manufacturer = "Nabu Casa"
    zigpy_app_controller.state.node_info.model = "Home Assistant Connect ZBT-2"
    zigpy_app_controller._ezsp = SimpleNamespace(
        _xncp_features=FirmwareFeatures.LED_CONTROL,
        xncp_set_led_state=AsyncMock(),
    )

    async with test_conftest.TestGateway(zha_data, zigpy_app_controller) as gateway:
        yield gateway


async def test_coordinator_led_not_exposed_without_feature(
    zha_gateway: Gateway,
) -> None:
    """Test that the coordinator LED entity is not exposed without support."""
    with pytest.raises(KeyError):
        get_entity(
            zha_gateway.coordinator_zha_device,
            platform=Platform.LIGHT,
            exact_entity_type=CoordinatorLED,
        )


async def test_coordinator_led_entity(zbt2_gateway: Gateway) -> None:
    """Test coordinator LED light discovery and control."""
    entity = get_entity(
        zbt2_gateway.coordinator_zha_device,
        platform=Platform.LIGHT,
        exact_entity_type=CoordinatorLED,
    )
    ezsp = zbt2_gateway.application_controller._ezsp

    assert entity.state["on"] is False
    assert entity.state["color_mode"] == ColorMode.XY
    assert entity.state["supported_color_modes"] == {ColorMode.XY}

    await entity.async_turn_on(brightness=128)
    await zbt2_gateway.async_block_till_done()

    expected_red, expected_green, expected_blue = _xy_brightness_to_rgb(
        DEFAULT_COORDINATOR_LED_XY_COLOR[0],
        DEFAULT_COORDINATOR_LED_XY_COLOR[1],
        128,
    )
    assert ezsp.xncp_set_led_state.await_args_list[0].kwargs == {
        "red": expected_red,
        "green": expected_green,
        "blue": expected_blue,
    }
    assert entity.state["on"] is True
    assert entity.state["brightness"] == 128
    assert entity.state["color_mode"] == ColorMode.XY

    await entity.async_turn_off()
    await zbt2_gateway.async_block_till_done()

    assert ezsp.xncp_set_led_state.await_args_list[1].kwargs == {
        "red": 0,
        "green": 0,
        "blue": 0,
    }
    assert entity.state["on"] is False


async def test_coordinator_led_first_turn_on_uses_firmware_dim_white_default(
    zbt2_gateway: Gateway,
) -> None:
    """Test that the first turn_on without a brightness uses the firmware dim white level."""
    entity = get_entity(
        zbt2_gateway.coordinator_zha_device,
        platform=Platform.LIGHT,
        exact_entity_type=CoordinatorLED,
    )
    ezsp = zbt2_gateway.application_controller._ezsp

    await entity.async_turn_on()
    await zbt2_gateway.async_block_till_done()

    expected_red, expected_green, expected_blue = _xy_brightness_to_rgb(
        DEFAULT_COORDINATOR_LED_XY_COLOR[0],
        DEFAULT_COORDINATOR_LED_XY_COLOR[1],
        DEFAULT_COORDINATOR_LED_BRIGHTNESS,
    )
    assert ezsp.xncp_set_led_state.await_args_list[0].kwargs == {
        "red": expected_red,
        "green": expected_green,
        "blue": expected_blue,
    }
    assert entity.state["brightness"] == DEFAULT_COORDINATOR_LED_BRIGHTNESS


async def test_coordinator_led_brightness_uses_current_xy_color(
    zbt2_gateway: Gateway,
) -> None:
    """Test that brightness-only updates preserve the current XY color."""
    entity = get_entity(
        zbt2_gateway.coordinator_zha_device,
        platform=Platform.LIGHT,
        exact_entity_type=CoordinatorLED,
    )
    ezsp = zbt2_gateway.application_controller._ezsp

    red_xy = (0.64, 0.33)
    await entity.async_turn_on(xy_color=red_xy, brightness=255)
    await zbt2_gateway.async_block_till_done()

    await entity.async_turn_on(brightness=64)
    await zbt2_gateway.async_block_till_done()

    assert ezsp.xncp_set_led_state.await_args_list[1].kwargs == {
        "red": 64,
        "green": 22,
        "blue": 11,
    }
    assert entity.state["xy_color"] == red_xy
    assert entity.state["brightness"] == 64


async def test_coordinator_led_restores_attributes_and_replays_on_state(
    zbt2_gateway: Gateway,
) -> None:
    """Test that coordinator LED restoration replays the previous on-state."""
    entity = get_entity(
        zbt2_gateway.coordinator_zha_device,
        platform=Platform.LIGHT,
        exact_entity_type=CoordinatorLED,
    )
    ezsp = zbt2_gateway.application_controller._ezsp

    entity.restore_external_state_attributes(
        state=True,
        off_with_transition=False,
        off_brightness=None,
        brightness=80,
        color_temp=None,
        xy_color=(0.64, 0.33),
        color_mode=ColorMode.XY,
        effect=None,
    )
    await zbt2_gateway.async_block_till_done()

    expected_red, expected_green, expected_blue = _xy_brightness_to_rgb(
        0.64,
        0.33,
        80,
    )
    assert ezsp.xncp_set_led_state.await_args_list[0].kwargs == {
        "red": expected_red,
        "green": expected_green,
        "blue": expected_blue,
    }
    assert entity.state["on"] is True
    assert entity.state["brightness"] == 80
    assert entity.state["xy_color"] == (0.64, 0.33)
    assert entity.state["color_mode"] == ColorMode.XY
