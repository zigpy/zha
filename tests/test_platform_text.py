"""Test the ZHA text platform."""

import pytest
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl import foundation as zcl_f
from zigpy.zcl.clusters import general

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    send_attributes_report,
)
from zha.application import EntityPlatform, Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory, EntityStateChangedEvent
from zha.application.platforms.text import TextConfigurationEntity, TextState
from zha.application.platforms.text.const import MAX_LENGTH_STATE_STATE, TextMode
from zha.exceptions import ZHAException
from zha.zigbee.device import Device


@pytest.fixture
async def zha_device(zha_gateway: Gateway) -> Device:
    """Return a joined device with a Basic cluster."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_OUTPUT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def create_text_entity(
    zha_device: Device, attribute_name: str, **kwargs
) -> TextConfigurationEntity:
    """Create a text entity for an attribute of the Basic cluster."""
    endpoint = zha_device.endpoints[1]
    entity = TextConfigurationEntity(
        endpoint=endpoint,
        device=zha_device,
        cluster=endpoint.zigpy_endpoint.in_clusters[general.Basic.cluster_id],
        attribute_name=attribute_name,
        unique_id_suffix=attribute_name,
        **kwargs,
    )
    entity.on_add()
    return entity


def test_text_platform_enums() -> None:
    """Test that quirk metadata can refer to the text platform."""
    assert Platform.TEXT == "text"
    assert EntityPlatform.TEXT == "text"
    assert Platform(EntityPlatform.TEXT.value) is Platform.TEXT


async def test_text_entity(zha_device: Device) -> None:
    """Test a text entity backed by a ZCL character string attribute."""
    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(general.Basic.AttributeDefs.location_desc.id, "Kitchen")

    entity = create_text_entity(zha_device, "location_desc", max_length=16)
    state_changes: list[EntityStateChangedEvent] = []
    entity.subscribe_state(state_changes.append)
    assert len(state_changes) == 1  # the initial state

    assert entity.PLATFORM == Platform.TEXT
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.unique_id == f"{zha_device.ieee}-1-0-location_desc"
    assert entity.is_supported()

    state = entity.state
    assert isinstance(state, TextState)
    assert state.native_value == "Kitchen"
    assert state.mode == TextMode.TEXT
    assert state.native_min == 0
    assert state.native_max == 16
    assert state.pattern is None

    await entity.async_set_value("Office")
    assert cluster.write_attributes.mock_calls[-1].args[0] == {
        "location_desc": "Office"
    }
    assert entity.state.native_value == "Office"
    assert len(state_changes) == 2

    # A report from the device updates the entity
    await send_attributes_report(
        zha_device.gateway,
        cluster,
        {general.Basic.AttributeDefs.location_desc.id: "Hallway"},
    )
    assert entity.state.native_value == "Hallway"
    assert len(state_changes) == 3

    # Other attributes don't
    await send_attributes_report(
        zha_device.gateway,
        cluster,
        {general.Basic.AttributeDefs.physical_env.id: 0x01},
    )
    assert len(state_changes) == 3


async def test_text_entity_options(zha_device: Device) -> None:
    """Test the length, pattern and mode options."""
    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(general.Basic.AttributeDefs.location_desc.id, "abc")

    entity = create_text_entity(
        zha_device,
        "location_desc",
        min_length=2,
        max_length=8,
        pattern=r"[a-z]+",
        mode="password",
    )

    state = entity.state
    assert state.native_min == 2
    assert state.native_max == 8
    assert state.pattern == r"[a-z]+"
    assert state.mode == TextMode.PASSWORD

    default = create_text_entity(zha_device, "location_desc")
    assert default.state.native_max == MAX_LENGTH_STATE_STATE
    assert default.state.mode == TextMode.TEXT


async def test_text_entity_bytes_attribute(zha_device: Device) -> None:
    """Test that an attribute typed as raw bytes is decoded and encoded as UTF-8."""
    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(
        general.Basic.AttributeDefs.product_code.id, "Café".encode()
    )

    entity = create_text_entity(zha_device, "product_code")
    assert entity.state.native_value == "Café"

    await entity.async_set_value("Zoë")
    assert cluster.write_attributes.mock_calls[-1].args[0] == {
        "product_code": "Zoë".encode()
    }
    assert entity.state.native_value == "Zoë"

    # Bytes that aren't valid UTF-8 don't break the state
    cluster.update_attribute(general.Basic.AttributeDefs.product_code.id, b"\xff")
    assert entity.state.native_value == "�"


async def test_text_entity_not_supported(zha_device: Device) -> None:
    """Test that the entity isn't created without a cached value."""
    entity = create_text_entity(zha_device, "location_desc")
    assert entity.state.native_value is None
    assert not entity.is_supported()

    unknown = create_text_entity(zha_device, "not_an_attribute")
    assert not unknown.is_supported()


@pytest.mark.parametrize(
    ("mode", "value_in_error"),
    [(TextMode.TEXT, True), (TextMode.PASSWORD, False)],
)
async def test_text_entity_write_failure(
    zha_device: Device, mode: TextMode, value_in_error: bool
) -> None:
    """Test that a failed write raises, without the value for a password."""
    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(general.Basic.AttributeDefs.location_desc.id, "old")
    cluster._write_attributes.return_value = [
        zcl_f.WriteAttributesResponse(
            [
                zcl_f.WriteAttributesStatusRecord(
                    status=zcl_f.Status.READ_ONLY,
                    attrid=general.Basic.AttributeDefs.location_desc.id,
                )
            ]
        )
    ]

    entity = create_text_entity(zha_device, "location_desc", mode=mode)

    with pytest.raises(ZHAException) as exc_info:
        await entity.async_set_value("secret")

    assert "location_desc" in str(exc_info.value)
    assert ("secret" in str(exc_info.value)) is value_in_error
    # No chained error carries the value either
    assert exc_info.value.__context__ is None
    assert entity.state.native_value == "old"


@pytest.mark.parametrize(
    ("value", "options"),
    [
        ("Kitchen", {"max_length": 4}),
        ("", {"min_length": 1}),
        ("kitchen 2", {"pattern": r"[a-z]+$"}),
        ("x" * 300, {}),
    ],
)
async def test_text_entity_value_outside_limits(
    zha_device: Device, value: str, options: dict
) -> None:
    """Test that a device value Home Assistant would refuse is shown as unknown."""
    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(
        general.Basic.AttributeDefs.manufacturer_version_details.id, value
    )

    entity = create_text_entity(zha_device, "manufacturer_version_details", **options)
    assert entity.state.native_value is None


async def test_text_entity_invalid_string(zha_device: Device) -> None:
    """Test that the ZCL invalid string is shown as unknown."""
    cluster = zha_device.device.endpoints[1].basic
    invalid, _ = zigpy.types.CharacterString.deserialize(b"\xff")
    cluster.update_attribute(general.Basic.AttributeDefs.location_desc.id, invalid)

    entity = create_text_entity(zha_device, "location_desc")
    assert entity.state.native_value is None


async def test_text_entity_subclass(zha_device: Device) -> None:
    """Test a subclass that sets its attribute on the class."""

    class LocationText(TextConfigurationEntity):
        _attribute_name = "location_desc"
        _unique_id_suffix = "location"

    cluster = zha_device.device.endpoints[1].basic
    cluster.update_attribute(general.Basic.AttributeDefs.location_desc.id, "Attic")

    endpoint = zha_device.endpoints[1]
    entity = LocationText(endpoint=endpoint, device=zha_device, cluster=cluster)
    assert entity.state.native_value == "Attic"
