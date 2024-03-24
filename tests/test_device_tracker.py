"""Test ZHA Device Tracker."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from slugify import slugify
import zigpy.profiles.zha
from zigpy.zcl.clusters import general

from tests.common import find_entity_id, send_attributes_report
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.device_tracker import SourceType
from zha.application.registries import SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE
from zha.zigbee.device import Device


@pytest.fixture
def zigpy_device_dt(zigpy_device_mock):
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [
                general.Basic.cluster_id,
                general.PowerConfiguration.cluster_id,
                general.Identify.cluster_id,
                general.PollControl.cluster_id,
                general.BinaryInput.cluster_id,
            ],
            SIG_EP_OUTPUT: [general.Identify.cluster_id, general.Ota.cluster_id],
            SIG_EP_TYPE: SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE,
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        }
    }
    return zigpy_device_mock(endpoints)


def get_entity(zha_dev: Device, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


@pytest.mark.looptime
async def test_device_tracker(
    zha_gateway: Gateway,
    device_joined,
    zigpy_device_dt,  # pylint: disable=redefined-outer-name
) -> None:
    """Test ZHA device tracker platform."""

    zha_device = await device_joined(zigpy_device_dt)
    cluster = zigpy_device_dt.endpoints.get(1).power
    entity_id = find_entity_id(Platform.DEVICE_TRACKER, zha_device)
    assert entity_id is not None
    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    assert entity.get_state()["connected"] is False

    # turn state flip
    await send_attributes_report(
        zha_gateway, cluster, {0x0000: 0, 0x0020: 23, 0x0021: 200, 0x0001: 2}
    )

    entity.async_update = AsyncMock(wraps=entity.async_update)
    zigpy_device_dt.last_seen = time.time() + 10
    await asyncio.sleep(48)
    await zha_gateway.async_block_till_done()
    assert entity.async_update.await_count == 1

    assert entity.get_state()["connected"] is True
    assert entity.is_connected is True
    assert entity.source_type == SourceType.ROUTER
    assert entity.battery_level == 100

    # knock it offline by setting last seen in the past
    zigpy_device_dt.last_seen = time.time() - 90
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["connected"] is False
    assert entity.is_connected is False

    # bring it back
    zigpy_device_dt.last_seen = time.time()  # type: ignore[unreachable]
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["connected"] is True
    assert entity.is_connected is True

    # knock it offline by setting last seen None
    zigpy_device_dt.last_seen = None
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["connected"] is False
    assert entity.is_connected is False
