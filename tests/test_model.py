"""Tests for the ZHA model module."""

from collections.abc import Callable
from enum import Enum

from zigpy.types import NWK
from zigpy.types.named import EUI64

from zha.model import convert_enum
from zha.zigbee.device import DeviceInfo, ZHAEvent


def test_ser_deser_zha_event():
    """Test serializing and deserializing ZHA events."""

    zha_event = ZHAEvent(
        device_ieee="00:00:00:00:00:00:00:00",
        unique_id="00:00:00:00:00:00:00:00",
        data={"key": "value"},
    )

    assert isinstance(zha_event.device_ieee, EUI64)
    assert zha_event.device_ieee == EUI64.convert("00:00:00:00:00:00:00:00")
    assert zha_event.unique_id == "00:00:00:00:00:00:00:00"
    assert zha_event.data == {"key": "value"}

    assert zha_event.model_dump() == {
        "message_type": "event",
        "event_type": "device_event",
        "event": "zha_event",
        "device_ieee": "00:00:00:00:00:00:00:00",
        "unique_id": "00:00:00:00:00:00:00:00",
        "data": {"key": "value"},
    }

    assert (
        zha_event.model_dump_json()
        == '{"message_type":"event","event_type":"device_event","event":"zha_event",'
        '"device_ieee":"00:00:00:00:00:00:00:00","unique_id":"00:00:00:00:00:00:00:00","data":{"key":"value"}}'
    )

    device_info = DeviceInfo(
        ieee="00:00:00:00:00:00:00:00",
        nwk="0x0000",
        manufacturer="test",
        model="test",
        name="test",
        quirk_applied=True,
        quirk_class="test",
        quirk_id="test",
        manufacturer_code=0x0000,
        power_source="test",
        lqi=1,
        rssi=2,
        last_seen="",
        available=True,
        device_type="test",
        signature={"foo": "bar"},
    )

    assert isinstance(device_info.ieee, EUI64)
    assert device_info.ieee == EUI64.convert("00:00:00:00:00:00:00:00")
    assert isinstance(device_info.nwk, NWK)

    assert device_info.model_dump() == {
        "ieee": "00:00:00:00:00:00:00:00",
        "nwk": 0x0000,
        "manufacturer": "test",
        "model": "test",
        "name": "test",
        "quirk_applied": True,
        "quirk_class": "test",
        "quirk_id": "test",
        "manufacturer_code": 0,
        "power_source": "test",
        "lqi": 1,
        "rssi": 2,
        "last_seen": "",
        "available": True,
        "device_type": "test",
        "signature": {"foo": "bar"},
    }

    assert device_info.model_dump_json() == (
        '{"ieee":"00:00:00:00:00:00:00:00","nwk":"0x0000",'
        '"manufacturer":"test","model":"test","name":"test","quirk_applied":true,'
        '"quirk_class":"test","quirk_id":"test","manufacturer_code":0,"power_source":"test",'
        '"lqi":1,"rssi":2,"last_seen":"","available":true,"device_type":"test","signature":{"foo":"bar"}}'
    )


def test_convert_enum() -> None:
    """Test the convert enum method."""

    class TestEnum(Enum):
        """Test enum."""

        VALUE = 1

    convert_test_enum: Callable[[str | Enum], Enum] = convert_enum(TestEnum)

    assert convert_test_enum(TestEnum.VALUE.name) == TestEnum.VALUE
    assert isinstance(convert_test_enum(TestEnum.VALUE.name), TestEnum)
    assert convert_test_enum(TestEnum.VALUE) == TestEnum.VALUE
