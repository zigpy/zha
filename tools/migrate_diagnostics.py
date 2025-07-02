"""Regenerate device diagnostics JSON, migrating from the old format."""

import sys

sys.path.insert(0, "tests")

import asyncio
from collections.abc import Callable
import contextlib
from contextlib import suppress
import json
import pathlib
import time
from typing import Optional
from unittest.mock import AsyncMock, patch

from zigpy.application import ControllerApplication
from zigpy.quirks import get_device as quirks_get_device
import zigpy.zcl
import zigpy.zdo.types as zdo_t

from tests.common import ZhaJsonEncoder, join_zigpy_device, patch_cluster_for_testing
from tests.conftest import TestGateway, make_zha_data, make_zigpy_app_controller

REPO_ROOT = pathlib.Path(__file__).parent.parent


def zigpy_device_from_legacy_device_data(
    app: ControllerApplication,
    device_data: dict,
    patch_cluster: bool = True,
    quirk: Optional[Callable] = None,
) -> zigpy.device.Device:
    """Make a fake device using the specified cluster classes."""
    ieee = zigpy.types.EUI64.convert(device_data["ieee"])
    nwk = device_data["nwk"]
    manufacturer = device_data["manufacturer"]
    model = device_data["model"]
    node_descriptor = device_data["signature"]["node_descriptor"]
    endpoints = device_data["signature"]["endpoints"]
    cluster_data = device_data["cluster_details"]

    device = zigpy.device.Device(app, ieee, nwk)
    device.manufacturer = manufacturer
    device.model = model

    node_desc = zdo_t.NodeDescriptor(
        logical_type=node_descriptor["logical_type"],
        complex_descriptor_available=node_descriptor["complex_descriptor_available"],
        user_descriptor_available=node_descriptor["user_descriptor_available"],
        reserved=node_descriptor["reserved"],
        aps_flags=node_descriptor["aps_flags"],
        frequency_band=node_descriptor["frequency_band"],
        mac_capability_flags=node_descriptor["mac_capability_flags"],
        manufacturer_code=node_descriptor["manufacturer_code"],
        maximum_buffer_size=node_descriptor["maximum_buffer_size"],
        maximum_incoming_transfer_size=node_descriptor[
            "maximum_incoming_transfer_size"
        ],
        server_mask=node_descriptor["server_mask"],
        maximum_outgoing_transfer_size=node_descriptor[
            "maximum_outgoing_transfer_size"
        ],
        descriptor_capability_field=node_descriptor["descriptor_capability_field"],
    )
    device.node_desc = node_desc
    device.last_seen = time.time()

    orig_endpoints = (
        device_data["original_signature"]["endpoints"]
        if "original_signature" in device_data
        else endpoints
    )
    for epid, ep in orig_endpoints.items():
        endpoint = device.add_endpoint(int(epid))
        profile = None
        with suppress(Exception):
            profile = zigpy.profiles.PROFILES[int(ep["profile_id"], 16)]

        endpoint.device_type = (
            profile.DeviceType(int(ep["device_type"], 16))
            if profile
            else int(ep["device_type"], 16)
        )
        endpoint.profile_id = (
            profile.PROFILE_ID if profile else int(ep["profile_id"], 16)
        )
        endpoint.request = AsyncMock(return_value=[0])

        for cluster_id in ep["input_clusters"]:
            endpoint.add_input_cluster(int(cluster_id, 16))

        for cluster_id in ep["output_clusters"]:
            endpoint.add_output_cluster(int(cluster_id, 16))

    if quirk:
        device = quirk(app, device.ieee, device.nwk, device)
    else:
        device = quirks_get_device(device)

    for epid, ep in cluster_data.items():
        endpoint.request = AsyncMock(return_value=[0])
        for cluster_id, cluster in ep["in_clusters"].items():
            real_cluster = device.endpoints[int(epid)].in_clusters[int(cluster_id, 16)]
            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr["value"] is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = attr["value"]
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = attr["value"]
            for unsupported_attr in cluster["unsupported_attributes"]:
                if isinstance(unsupported_attr, str) and unsupported_attr.startswith(
                    "0x"
                ):
                    attrid = int(unsupported_attr, 16)
                    real_cluster.unsupported_attributes.add(attrid)
                    if attrid in real_cluster.attributes:
                        real_cluster.unsupported_attributes.add(
                            real_cluster.attributes[attrid].name
                        )
                else:
                    real_cluster.unsupported_attributes.add(unsupported_attr)

        for cluster_id, cluster in ep["out_clusters"].items():
            real_cluster = device.endpoints[int(epid)].out_clusters[int(cluster_id, 16)]
            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr["value"] is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = attr["value"]
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = attr["value"]
            for unsupported_attr in cluster["unsupported_attributes"]:
                if isinstance(unsupported_attr, str) and unsupported_attr.startswith(
                    "0x"
                ):
                    attrid = int(unsupported_attr, 16)
                    real_cluster.unsupported_attributes.add(attrid)
                    if attrid in real_cluster.attributes:
                        real_cluster.unsupported_attributes.add(
                            real_cluster.attributes[attrid].name
                        )
                else:
                    real_cluster.unsupported_attributes.add(unsupported_attr)

    return device


@contextlib.asynccontextmanager
async def create_zha_gateway():
    """Turn a pytest fixture into a normal context manager."""
    # This isn't the way Pytest is meant to be used :)
    with make_zigpy_app_controller() as zigpy_app_controller:
        async with TestGateway(
            data=make_zha_data(),
            app=zigpy_app_controller,
        ) as zha_gateway:
            yield zha_gateway


async def main():
    """Entry point."""
    async with create_zha_gateway() as zha_gateway:
        for device_json in (REPO_ROOT / "tests" / "data" / "devices").glob("**/*.json"):
            zigpy_device = zigpy_device_from_legacy_device_data(
                zha_gateway.application_controller,
                json.loads(device_json.read_text()),
            )

            with patch("zigpy.zcl.Cluster._update_attribute"):
                zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
                await zha_gateway.async_block_till_done(wait_background_tasks=True)

            new_json = json.dumps(
                zha_device.get_diagnostics_json(), indent=2, cls=ZhaJsonEncoder
            )
            device_json.write_text(new_json)


if __name__ == "__main__":
    asyncio.run(main())
