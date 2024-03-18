"""Test ZHA select entities."""

from collections.abc import Awaitable, Callable

import pytest
from slugify import slugify
from zigpy.const import SIG_EP_PROFILE
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security

from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.platforms import PlatformEntity
from zha.zigbee.device import ZHADevice

from .common import find_entity_id
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE


@pytest.fixture
async def siren(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> tuple[ZHADevice, security.IasWd]:
    """Siren fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd


def get_entity(zha_dev: ZHADevice, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]  # type: ignore


async def test_select(
    siren: tuple[ZHADevice, security.IasWd],  # pylint: disable=redefined-outer-name
    zha_gateway: ZHAGateway,
) -> None:
    """Test zha select platform."""
    zha_device, cluster = siren
    assert cluster is not None
    select_name = security.IasWd.Warning.WarningMode.__name__
    entity_id = find_entity_id(
        Platform.SELECT,
        zha_device,
        qualifier=select_name.lower(),
    )
    assert entity_id is not None

    entity = get_entity(zha_device, entity_id)
    assert entity is not None
    assert entity.get_state()["state"] is None  # unknown in HA
    assert entity.to_json()["options"] == [
        "Stop",
        "Burglar",
        "Fire",
        "Emergency",
        "Police Panic",
        "Fire Panic",
        "Emergency Panic",
    ]
    assert entity._enum == security.IasWd.Warning.WarningMode

    # change value from client
    await entity.async_select_option(security.IasWd.Warning.WarningMode.Burglar.name)
    await zha_gateway.async_block_till_done()
    assert (
        entity.get_state()["state"] == security.IasWd.Warning.WarningMode.Burglar.name
    )
