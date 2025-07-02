"""Import device diagnostics JSON from Home Assistant ZHA diagnostics."""

import sys

sys.path.insert(0, "tests")

import asyncio
import contextlib
from contextlib import suppress
import hashlib
import json
import logging
import pathlib
import time
from unittest.mock import AsyncMock, patch

from slugify import slugify
from zigpy.application import ControllerApplication
from zigpy.quirks import get_device as quirks_get_device
import zigpy.zcl
import zigpy.zdo.types as zdo_t

from tests.common import (
    ZhaJsonEncoder,
    join_zigpy_device,
    patch_cluster_for_testing,
    zigpy_device_from_device_data,
)
from tests.conftest import TestGateway, make_zha_data, make_zigpy_app_controller

_LOGGER = logging.getLogger(__name__)
REPO_ROOT = pathlib.Path(__file__).parent.parent


def zigpy_device_from_legacy_diagnostics(
    app: ControllerApplication,
    data: dict,
    patch_cluster: bool = True,
) -> zigpy.device.Device:
    """Make a fake device using the specified cluster classes."""
    device_data = data["data"]

    nwk = device_data["nwk"]
    manufacturer = device_data["manufacturer"]
    model = device_data["model"]
    node_descriptor = device_data["signature"]["node_descriptor"]
    endpoints = device_data["signature"]["endpoints"]
    cluster_data = device_data["cluster_details"]

    # Generate a unique IEEE address based on the manufacturer and model, since the
    # real (unique) IEEE is redacted
    ieee_hash = hashlib.sha256(f"{manufacturer} {model}".encode()).hexdigest()
    ieee = zigpy.types.EUI64.convert("abcdef12" + ieee_hash[:8])

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

    for epid, ep in endpoints.items():
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


async def main(paths: list[str]):
    """Entry point."""
    async with create_zha_gateway() as zha_gateway:
        for path in map(pathlib.Path, paths):
            try:
                zigpy_device = zigpy_device_from_legacy_diagnostics(
                    zha_gateway.application_controller,
                    json.loads(path.read_text()),
                )
            except Exception:
                _LOGGER.warning("Failed to import %s", path, exc_info=True)
                continue

            output_path = (
                REPO_ROOT
                / "tests"
                / "data"
                / "devices"
                / (
                    slugify(f"{zigpy_device.manufacturer}-{zigpy_device.model}")
                    + ".json"
                )
            )

            if output_path.is_file():
                continue

            with patch("zigpy.zcl.Cluster._update_attribute"):
                zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
                await zha_gateway.async_block_till_done(wait_background_tasks=True)

            # First, try to join the device
            initial_json = zha_device.get_diagnostics_json()

            await zha_gateway.async_remove_device(zha_device)
            await zha_device.on_remove()
            del zha_gateway.devices[zha_device.ieee]

            # Next, try to re-join the device and see if its quirk still matches
            rejoined_zigpy_device = zigpy_device_from_device_data(
                app=zha_gateway.application_controller,
                device_data=initial_json,
            )

            with patch("zigpy.zcl.Cluster._update_attribute"):
                rejoined_zha_device = await join_zigpy_device(
                    zha_gateway, rejoined_zigpy_device
                )
                await zha_gateway.async_block_till_done(wait_background_tasks=True)

            rejoined_json = rejoined_zha_device.get_diagnostics_json()
            if initial_json != rejoined_json:
                _LOGGER.warning(
                    "Rejoined device %s does not match original diagnostics JSON, quirk has modified the device signature",
                    path,
                )
                continue

            _LOGGER.info("Importing %s as %s", path, output_path.name)
            new_json = json.dumps(initial_json, indent=2, cls=ZhaJsonEncoder)
            output_path.write_text(new_json)


if __name__ == "__main__":
    import coloredlogs

    coloredlogs.install(level="DEBUG")
    asyncio.run(main(sys.argv[1:]))
