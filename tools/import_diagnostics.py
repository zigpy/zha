"""Import device diagnostics JSON from Home Assistant ZHA diagnostics."""

from __future__ import annotations

import sys

sys.path.insert(0, "tests")

import ast
import asyncio
import contextlib
from contextlib import suppress
import hashlib
import json
import logging
import pathlib
import re
import time
from typing import Any
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

# Old node descriptors were stored as strings
NODE_DESCRIPTOR_REGEX = re.compile(
    r"NodeDescriptor\(logical_type=<.*?: (?P<logical_type>\d+)\>, complex_descriptor_available=(?P<complex_descriptor_available>\w+), user_descriptor_available=(?P<user_descriptor_available>\w+), reserved=(?P<reserved>\d+), aps_flags=(?P<aps_flags>\d+), frequency_band=<.*?(?P<frequency_band>\d+)>, mac_capability_flags=<.*?: (?P<mac_capability_flags>\d+)>, manufacturer_code=(?P<manufacturer_code>\d+), maximum_buffer_size=(?P<maximum_buffer_size>\d+), maximum_incoming_transfer_size=(?P<maximum_incoming_transfer_size>\d+), server_mask=(?P<server_mask>\d+), maximum_outgoing_transfer_size=(?P<maximum_outgoing_transfer_size>\d+), descriptor_capability_field=<.*?: (?P<descriptor_capability_field>\d+)>,"
)


def ieee_from_manufacturer_model(manufacturer: str, model: str) -> zigpy.types.EUI64:
    """Generate a fake IEEE address based on the manufacturer and model."""
    ieee_hash = hashlib.sha256(f"{manufacturer} {model}".encode()).hexdigest()
    return zigpy.types.EUI64.convert("abcdef12" + ieee_hash[:8])


def parse_legacy_value(value: Any) -> Any:
    """Parse a legacy attribute value from diagnostics JSON."""
    if isinstance(value, dict):
        if value.get("__type") in (
            "<class 'bytes'>",
            "<class 'zigpy.types.basic.LVBytes'>",
            "<class 'zigpy.types.basic.LimitedLVBytes.<locals>.LimitedLVBytes'>",
        ):
            result = ast.literal_eval(value["repr"])

            # Bad Tuya custom quirk, ignore
            if (
                result
                == b"\x00\x05\x00d\x00\x05\x00\x1e\x00<\x00\x00\x00\x00\x00\x00\x00"
            ):
                return None

            return result
        elif set(value.keys()) == {"field_1", "temperature"}:
            # Old, invalid attribute converter for Tuya air CO quality sensors
            return value["field_1"].to_bytes(2, "big") + value["temperature"].to_bytes(
                2, "big"
            )
        else:
            raise ValueError(f"Unknown legacy value dict: {value}")

    return value


def zigpy_device_from_legacy_diagnostics(  # noqa: C901
    app: ControllerApplication,
    data: dict,
    patch_cluster: bool = True,
) -> zigpy.device.Device | None:
    """Make a fake device using the specified cluster classes."""
    device_data = data["data"]

    # Unrelated diagnostics
    if "nwk" not in device_data:
        return None

    nwk = device_data["nwk"]
    manufacturer = device_data["manufacturer"]
    model = device_data["model"]

    if isinstance(device_data["signature"]["node_descriptor"], str):
        match = NODE_DESCRIPTOR_REGEX.search(
            device_data["signature"]["node_descriptor"]
        )
        assert match is not None
        node_desc = zdo_t.NodeDescriptor(
            logical_type=int(match.group("logical_type")),
            complex_descriptor_available=int(
                match.group("complex_descriptor_available")
            ),
            user_descriptor_available=int(match.group("user_descriptor_available")),
            reserved=int(match.group("reserved")),
            aps_flags=int(match.group("aps_flags")),
            frequency_band=int(match.group("frequency_band")),
            mac_capability_flags=int(match.group("mac_capability_flags")),
            manufacturer_code=int(match.group("manufacturer_code")),
            maximum_buffer_size=int(match.group("maximum_buffer_size")),
            maximum_incoming_transfer_size=int(
                match.group("maximum_incoming_transfer_size")
            ),
            server_mask=int(match.group("server_mask")),
            maximum_outgoing_transfer_size=int(
                match.group("maximum_outgoing_transfer_size")
            ),
            descriptor_capability_field=int(match.group("descriptor_capability_field")),
        )
    else:
        node_descriptor = device_data["signature"]["node_descriptor"]
        node_desc = zdo_t.NodeDescriptor(
            logical_type=node_descriptor["logical_type"],
            complex_descriptor_available=node_descriptor[
                "complex_descriptor_available"
            ],
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

    endpoints = device_data["signature"]["endpoints"]

    # Older diagnostics did not expose the attribute cache and thus cannot be used
    if "cluster_details" not in device_data:
        return None

    cluster_data = device_data["cluster_details"]

    # Generate a unique IEEE address based on the manufacturer and model, since the
    # real (unique) IEEE is redacted
    ieee = ieee_from_manufacturer_model(manufacturer, model)

    device = zigpy.device.Device(app, ieee, nwk)
    device.manufacturer = manufacturer
    device.model = model

    device.node_desc = node_desc
    device.last_seen = time.time()

    for epid, ep in endpoints.items():
        # Old diagnostics just used strings for clusters, there was no cache
        if "in_clusters" in ep and isinstance(ep["in_clusters"], list):
            return None

        endpoint = device.add_endpoint(int(epid))
        profile = None
        with suppress(Exception):
            profile = zigpy.profiles.PROFILES[int(ep["profile_id"], 16)]

        endpoint.device_type = (
            profile.DeviceType(int(ep["device_type"], 16))
            if profile
            else int(ep["device_type"], 16)
        )

        if profile:
            endpoint.profile_id = profile.PROFILE_ID
        elif isinstance(ep["profile_id"], int):
            endpoint.profile_id = ep["profile_id"]
        else:
            endpoint.profile_id = int(ep["profile_id"], 16)

        endpoint.request = AsyncMock(return_value=[0])

        for cluster_id in ep["input_clusters"]:
            endpoint.add_input_cluster(int(cluster_id, 16))

        for cluster_id in ep["output_clusters"]:
            endpoint.add_output_cluster(int(cluster_id, 16))

    device = quirks_get_device(device)

    for epid, ep in cluster_data.items():
        endpoint.request = AsyncMock(return_value=[0])
        for cluster_id, cluster in ep["in_clusters"].items():
            try:
                real_cluster = device.endpoints[int(epid)].in_clusters[
                    int(cluster_id, 16)
                ]
            except KeyError:
                _LOGGER.warning(
                    "Failed to find server cluster 0x%s on endpoint %s: %s",
                    cluster_id,
                    epid,
                    cluster,
                )
                continue

            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr.get("value") is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = parse_legacy_value(
                    attr["value"]
                )
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = parse_legacy_value(
                    attr["value"]
                )
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
            try:
                real_cluster = device.endpoints[int(epid)].out_clusters[
                    int(cluster_id, 16)
                ]
            except KeyError:
                _LOGGER.warning(
                    "Failed to find client cluster 0x%s on endpoint %s: %s",
                    cluster_id,
                    epid,
                    cluster,
                )
                continue

            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr.get("value") is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = parse_legacy_value(
                    attr["value"]
                )
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = parse_legacy_value(
                    attr["value"]
                )
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

    if device.model is None and device.manufacturer is None:
        return None

    return device


def zigpy_device_from_diagnostics(
    app: ControllerApplication,
    data: dict,
    patch_cluster: bool = True,
) -> zigpy.device.Device | None:
    """Create a zigpy device from diagnostics JSON, both modern and legacy formats."""
    if "data" not in data:
        return None

    zha_data = data["data"]

    if "version" not in zha_data:
        return zigpy_device_from_legacy_diagnostics(app, data, patch_cluster)

    # Home Assistant diagnostics contain redacted IEEE info, fake an IEEE instead
    if "REDACTED" in zha_data["ieee"]:
        zha_data["ieee"] = str(
            ieee_from_manufacturer_model(
                manufacturer=zha_data["manufacturer"], model=zha_data["model"]
            )
        )

    # Neighbors contain EUI64 addresses and EPIDs
    zha_data["neighbors"] = []
    zha_data["routes"] = []

    # Use our normal testing function to load the data
    return zigpy_device_from_device_data(app, zha_data, patch_cluster)


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
            _LOGGER.debug("Considering %r", path)

            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                _LOGGER.debug("Skipping, not valid JSON")
                continue

            if "home_assistant" not in data:
                _LOGGER.debug("Skipping, missing 'home_assistant' key")
                continue

            zigpy_device = zigpy_device_from_diagnostics(
                zha_gateway.application_controller, data
            )

            if zigpy_device is None:
                _LOGGER.debug("Skipping, diagnostics are not valid")
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
