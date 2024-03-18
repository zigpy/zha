"""Test ZHA select entities."""

from collections.abc import Awaitable, Callable
from typing import Optional

import pytest
from slugify import slugify
from zhaws.client.controller import Controller
from zhaws.client.model.types import SelectEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device
from zigpy.const import SIG_EP_PROFILE
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security

from .common import find_entity_id
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE


@pytest.fixture
async def siren(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> tuple[Device, security.IasWd]:
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


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> SelectEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]  # type: ignore


async def test_select(
    siren: tuple[Device, security.IasWd],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha select platform."""
    zha_device, cluster = siren
    assert cluster is not None
    controller, server = connected_client_and_server
    select_name = security.IasWd.Warning.WarningMode.__name__
    entity_id = find_entity_id(
        Platform.SELECT,
        zha_device,
        qualifier=select_name.lower(),
    )
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None
    assert entity.state.state is None  # unknown in HA
    assert entity.options == [
        "Stop",
        "Burglar",
        "Fire",
        "Emergency",
        "Police Panic",
        "Fire Panic",
        "Emergency Panic",
    ]
    assert entity.enum == select_name

    # change value from client
    await controller.selects.select_option(
        entity, security.IasWd.Warning.WarningMode.Burglar.name
    )
    await server.block_till_done()
    assert entity.state.state == security.IasWd.Warning.WarningMode.Burglar.name
