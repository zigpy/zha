"""Regenerate device diagnostics JSON, when new entities are added."""

import sys

sys.path.insert(0, "tests")

import asyncio
import contextlib
import json
import pathlib
from unittest.mock import patch

from tests.common import ZhaJsonEncoder, join_zigpy_device, zigpy_device_from_json
from tests.conftest import TestGateway, make_zha_data, make_zigpy_app_controller

REPO_ROOT = pathlib.Path(__file__).parent.parent


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
            zigpy_device = await zigpy_device_from_json(
                zha_gateway.application_controller,
                device_json,
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
