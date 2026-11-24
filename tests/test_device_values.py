"""Test entities showing and setting device values."""

import enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from zhaquirks.builder import QuirkBuilder
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.zcl.clusters import general

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    rejoin_zha_device,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory
from zha.application.platforms.binary_sensor import (
    BinarySensorDeviceClass,
    DeviceValueBinarySensor,
)
from zha.application.platforms.number import DeviceValueNumber
from zha.application.platforms.number.const import NumberDeviceClass, NumberMode
from zha.application.platforms.select import DeviceValueSelect
from zha.application.platforms.switch import DeviceValueSwitch
from zha.const import STATE_CHANGED
from zha.exceptions import ZHAException
from zha.units import UnitOfTime
from zha.zigbee.device import Device
from zha.zigbee.store import device_value


class Mode(enum.IntEnum):
    """Mode of the test device."""

    Click = 0
    Long_press = 1


def _as_stored(value: Any) -> Any:
    """Read a value as stored, as Tuya device values are."""
    return value


DOWN_MOVEMENT = device_value("down_movement", _as_stored)
TOUCH_CONTROL = device_value("touch_control", _as_stored)
MODE = device_value("mode", int)
TAMPER = device_value("tamper", int)

# Written by the quirk's writers, so tests can check what was sent
WRITES: list[tuple[str, Any]] = []


async def write_down_movement(device: ZigpyDevice, value: int) -> None:
    """Send the value, then set it as the device has it."""
    WRITES.append(("down_movement", value))
    device.store[DOWN_MOVEMENT] = value


async def write_mode(device: ZigpyDevice, value: Mode) -> None:
    """Send the value, then set it as the device has it."""
    WRITES.append(("mode", value))
    device.store[MODE] = value


(
    QuirkBuilder("Fake_Manufacturer_values", "Fake_Model_values")
    .adds_entity(
        DeviceValueNumber,
        value=DOWN_MOVEMENT,
        writer=write_down_movement,
        min_value=50,
        max_value=100,
        unique_id_suffix="1-down_movement",
        translation_key="down_movement",
        fallback_name="Down movement",
    )
    .adds_entity(
        DeviceValueSwitch,
        value=TOUCH_CONTROL,
        unique_id_suffix="1-touch_control",
        translation_key="touch_control",
        fallback_name="Touch control",
    )
    .adds_entity(
        DeviceValueSelect,
        value=MODE,
        enum=Mode,
        writer=write_mode,
        unique_id_suffix="1-mode",
        translation_key="mode",
        fallback_name="Mode",
    )
    .adds_entity(
        DeviceValueBinarySensor,
        value=TAMPER,
        device_class=BinarySensorDeviceClass.TAMPER,
        unique_id_suffix="1-tamper",
        fallback_name="Tamper",
    )
    .add_to_registry()
)


@pytest.fixture(autouse=True)
def clear_writes() -> None:
    """Forget the writes of earlier tests."""
    WRITES.clear()


async def _join_device(
    zha_gateway: Gateway,
    manufacturer: str = "Fake_Manufacturer_values",
    model: str = "Fake_Model_values",
) -> Device:
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SIMPLE_SENSOR,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        manufacturer=manufacturer,
        model=model,
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def _set_raw(zha_device: Device, decl: Any, value: Any) -> None:
    """Store a value without going through its declaration."""
    zha_device.device.store.namespace(decl.namespace)[decl.key] = value


async def test_device_value_entities_from_quirk(zha_gateway: Gateway) -> None:
    """A quirk adds device value entities, bound to the device, with stable IDs."""
    zha_device = await _join_device(zha_gateway)
    ieee = zha_device.ieee

    number = get_entity(
        zha_device, Platform.NUMBER, exact_entity_type=DeviceValueNumber
    )
    switch = get_entity(
        zha_device, Platform.SWITCH, exact_entity_type=DeviceValueSwitch
    )
    select = get_entity(
        zha_device, Platform.SELECT, exact_entity_type=DeviceValueSelect
    )
    binary_sensor = get_entity(
        zha_device, Platform.BINARY_SENSOR, exact_entity_type=DeviceValueBinarySensor
    )

    # The unique IDs match those of quirk entities on endpoint 1
    assert number.unique_id == f"{ieee}-1-down_movement"
    assert switch.unique_id == f"{ieee}-1-touch_control"
    assert select.unique_id == f"{ieee}-1-mode"
    assert binary_sensor.unique_id == f"{ieee}-1-tamper"

    for entity in (number, switch, select, binary_sensor):
        assert entity.identifiers.endpoint_id is None

    assert number.entity_category == EntityCategory.CONFIG
    assert switch.entity_category == EntityCategory.CONFIG
    assert select.entity_category == EntityCategory.CONFIG

    # Nothing stored yet
    assert number.state.native_value is None
    assert switch.state.is_on is False
    assert select.state.current_option is None
    assert binary_sensor.state.is_on is False

    # Home Assistant's groupable device list reads an endpoint of every entity
    for entity in (number, switch, select, binary_sensor):
        with pytest.warns(DeprecationWarning):
            assert entity.endpoint is zha_device.endpoints[1]

    # Values survive the ZHA device, as they do a restart
    await number.async_set_native_value(60)
    await switch.async_turn_on()
    await select.async_select_option("Long press")
    _set_raw(zha_device, TAMPER, True)

    zha_device = await rejoin_zha_device(zha_gateway, zha_device)

    number = get_entity(
        zha_device, Platform.NUMBER, exact_entity_type=DeviceValueNumber
    )
    switch = get_entity(
        zha_device, Platform.SWITCH, exact_entity_type=DeviceValueSwitch
    )
    select = get_entity(
        zha_device, Platform.SELECT, exact_entity_type=DeviceValueSelect
    )
    binary_sensor = get_entity(
        zha_device, Platform.BINARY_SENSOR, exact_entity_type=DeviceValueBinarySensor
    )

    assert number.state.native_value == 60
    assert switch.state.is_on is True
    assert select.state.current_option == "Long press"
    assert binary_sensor.state.is_on is True


async def test_device_value_number(zha_gateway: Gateway) -> None:
    """A number shows a device value scaled and writes it through its writer."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    entity = get_entity(
        zha_device, Platform.NUMBER, exact_entity_type=DeviceValueNumber
    )

    listener = MagicMock()
    entity.on_event(STATE_CHANGED, listener)

    assert entity.state.native_min_value == 50
    assert entity.state.native_max_value == 100
    assert entity.state.native_step == 1
    assert entity.state.mode == NumberMode.AUTO

    zigpy_device.store[DOWN_MOVEMENT] = 70
    assert entity.state.native_value == 70
    assert len(listener.mock_calls) == 1

    # The writer sends the value and sets it in the store, which updates the state
    await entity.async_set_native_value(80.0)
    assert WRITES == [("down_movement", 80)]
    assert type(WRITES[0][1]) is int
    assert zigpy_device.store[DOWN_MOVEMENT] == 80
    assert entity.state.native_value == 80
    assert len(listener.mock_calls) == 2

    # Values that are not numbers read as unknown
    for value in ("x", True, [1]):
        _set_raw(zha_device, DOWN_MOVEMENT, value)
        assert entity.state.native_value is None


async def test_device_value_number_writer_error(zha_gateway: Gateway) -> None:
    """A failing writer's error reaches the caller and the value is not set."""
    zha_device = await _join_device(zha_gateway)
    value = device_value("delay", int)

    async def failing_writer(device: ZigpyDevice, new_value: int) -> None:
        raise TimeoutError

    entity = DeviceValueNumber(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="delay",
        value=value,
        writer=failing_writer,
        translation_key="delay",
    )
    entity.on_add()
    zha_device.device.store[value] = 5

    with pytest.raises(TimeoutError):
        await entity.async_set_native_value(10)

    assert entity.state.native_value == 5

    await entity.on_remove()


async def test_device_value_number_host_side(zha_gateway: Gateway) -> None:
    """Without a writer, a number's value is kept in the store only."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    value = device_value("reset_timeout", float)
    entity = DeviceValueNumber(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="reset_timeout",
        value=value,
        multiplier=0.1,
        min_value=1,
        max_value=60,
        step=0.1,
        unit=UnitOfTime.MINUTES,
        mode="box",
        device_class=NumberDeviceClass.DURATION,
        translation_key="reset_timeout",
    )
    entity.on_add()

    assert entity.state.native_unit_of_measurement == UnitOfTime.MINUTES
    assert entity.state.mode == NumberMode.BOX
    assert entity.state.native_step == 0.1
    assert entity.device_class == NumberDeviceClass.DURATION

    # Stored unscaled and rounded to an int, as a ZCL attribute is written
    await entity.async_set_native_value(2.3)
    assert zigpy_device.store.namespace(value.namespace)[value.key] == 23
    assert type(zigpy_device.store.namespace(value.namespace)[value.key]) is int
    assert entity.state.native_value == pytest.approx(2.3)

    # Fractions below the multiplier's resolution are rounded off
    await entity.async_set_native_value(0.34)
    assert zigpy_device.store.namespace(value.namespace)[value.key] == 3
    assert entity.state.native_value == pytest.approx(0.3)

    # Also for large values, whose fraction is small relative to them
    await entity.async_set_native_value(123456789.04)
    assert zigpy_device.store.namespace(value.namespace)[value.key] == 1234567890

    # A value the declaration cannot decode reads as unknown
    _set_raw(zha_device, value, "x")
    assert entity.state.native_value is None

    # An invalid mode is ignored
    invalid_mode = DeviceValueNumber(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="invalid_mode",
        value=value,
        mode="not a mode",
        translation_key="reset_timeout",
    )
    assert invalid_mode.state.mode == NumberMode.AUTO

    # Without a store, a host-side value cannot be written
    with (
        patch("zha.application.platforms.get_device_store", return_value=None),
        pytest.raises(ZHAException, match="has no store"),
    ):
        await entity.async_set_native_value(5)

    await entity.on_remove()


async def test_device_value_switch(zha_gateway: Gateway) -> None:
    """A switch shows a device value and, without a writer, stores what it sets."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    entity = get_entity(
        zha_device, Platform.SWITCH, exact_entity_type=DeviceValueSwitch
    )

    assert entity.state.inverted is False
    assert entity.state.on_value == 1
    assert entity.state.off_value == 0

    await entity.async_turn_on()
    assert zigpy_device.store[TOUCH_CONTROL] == 1
    assert entity.state.is_on is True

    await entity.async_turn_off()
    assert zigpy_device.store[TOUCH_CONTROL] == 0
    assert entity.state.is_on is False

    # Stored by truth, as a datapoint report stores a bool
    _set_raw(zha_device, TOUCH_CONTROL, True)
    assert entity.state.is_on is True

    # A value that is not an int reads as off
    _set_raw(zha_device, TOUCH_CONTROL, "on")
    assert entity.state.is_on is False


async def test_device_value_switch_options(zha_gateway: Gateway) -> None:
    """A switch takes on and off values, a forced inversion and a writer."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    value = device_value("led", int)
    writes = []

    async def writer(device: ZigpyDevice, new_value: int) -> None:
        assert device is zigpy_device
        writes.append(new_value)
        device.store[value] = new_value

    entity = DeviceValueSwitch(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="led",
        value=value,
        writer=writer,
        on_value=2,
        off_value=3,
        force_inverted=True,
        translation_key="led",
    )
    entity.on_add()

    assert entity.state.inverted is True
    assert entity.state.force_inverted is True
    assert entity.state.on_value == 2
    assert entity.state.off_value == 3

    # Inverted: an absent value is on, as for an attribute
    assert entity.state.is_on is True

    await entity.async_turn_on()
    assert writes == [3]
    assert entity.state.is_on is True

    await entity.async_turn_off()
    assert writes == [3, 2]
    assert entity.state.is_on is False

    # Only the on value is on
    zigpy_device.store[value] = 1
    assert entity.state.is_on is True

    await entity.on_remove()


async def test_device_value_select(zha_gateway: Gateway) -> None:
    """A select shows a device value as an enum member and writes members."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    entity = get_entity(
        zha_device, Platform.SELECT, exact_entity_type=DeviceValueSelect
    )

    assert entity.state.options == ["Click", "Long press"]
    assert entity.state.enum == "Mode"

    zigpy_device.store[MODE] = 0
    assert entity.state.current_option == "Click"

    await entity.async_select_option("Long press")
    assert [("mode", Mode.Long_press)] == WRITES
    assert type(WRITES[0][1]) is Mode
    assert zigpy_device.store.namespace(MODE.namespace)[MODE.key] == 1
    assert entity.state.current_option == "Long press"

    # Values that are not members read as unknown
    for value in (5, "x", [1]):
        _set_raw(zha_device, MODE, value)
        assert entity.state.current_option is None

    # An option that is not a member is refused with an error Home Assistant shows
    with pytest.raises(ZHAException, match="Invalid option"):
        await entity.async_select_option("Medium")
    assert len(WRITES) == 1

    # Only int enums: members are stored as JSON and sent as ints
    class Color(enum.Enum):
        Red = "red"

    with pytest.raises(TypeError, match="int enum"):
        DeviceValueSelect(
            zha_device,
            unique_id=str(zha_device.ieee),
            unique_id_suffix="color",
            value=device_value("color", Color),
            enum=Color,
            translation_key="color",
        )

    # The value is in the store, so Home Assistant's restored state is ignored
    zigpy_device.store[MODE] = 0
    entity.restore_external_state_attributes(state="Long press")
    assert entity.state.current_option == "Click"

    # Without a writer, the member is stored as its value
    host_side = DeviceValueSelect(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="host_mode",
        value=device_value("host_mode", Mode),
        enum=Mode,
        translation_key="mode",
    )
    host_side.on_add()
    await host_side.async_select_option("Long press")
    assert zigpy_device.store[device_value("host_mode", Mode)] is Mode.Long_press
    assert host_side.state.current_option == "Long press"
    await host_side.on_remove()


async def test_device_value_binary_sensor(zha_gateway: Gateway) -> None:
    """A binary sensor shows a device value by truth or through a converter."""
    zha_device = await _join_device(zha_gateway)
    zigpy_device = zha_device.device
    entity = get_entity(
        zha_device, Platform.BINARY_SENSOR, exact_entity_type=DeviceValueBinarySensor
    )

    assert entity.device_class == BinarySensorDeviceClass.TAMPER
    assert entity.state.is_on is False

    zigpy_device.store[TAMPER] = 1
    assert entity.state.is_on is True

    zigpy_device.store[TAMPER] = 0
    assert entity.state.is_on is False

    # A value the declaration cannot decode reads as off
    _set_raw(zha_device, TAMPER, "x")
    assert entity.state.is_on is False

    value = device_value("alarm", int)
    converted = DeviceValueBinarySensor(
        zha_device,
        unique_id=str(zha_device.ieee),
        unique_id_suffix="alarm",
        value=value,
        value_converter=lambda value: value > 100,
        fallback_name="Alarm",
    )
    converted.on_add()

    zigpy_device.store[value] = 150
    assert converted.state.is_on is True
    zigpy_device.store[value] = 50
    assert converted.state.is_on is False

    # A value the converter cannot handle reads as off
    _set_raw(zha_device, value, [1])
    assert converted.state.is_on is False

    await converted.on_remove()
