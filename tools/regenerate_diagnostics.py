"""Regenerate device diagnostics JSON, when new entities are added."""

import sys

sys.path.insert(0, "tests")

import asyncio
import contextlib
import json
import pathlib
from unittest.mock import patch

from tests.common import ZhaJsonEncoder, join_zigpy_device, zigpy_device_from_json
from tests.conftest import (
    zha_data_fixture,
    zha_gateway as zha_gateway_fixture,
    zigpy_app_controller_fixture,
)

REPO_ROOT = pathlib.Path(__file__).parent.parent


@contextlib.asynccontextmanager
async def create_zha_gateway():
    """Turn a pytest fixture into a normal context manager."""
    # This isn't the way Pytest is meant to be used :)
    async for zigpy_app_controller in zigpy_app_controller_fixture.__wrapped__():
        async for zha_gateway in zha_gateway_fixture.__wrapped__(
            zha_data=zha_data_fixture.__wrapped__(),
            zigpy_app_controller=zigpy_app_controller,
            caplog=None,
        ):
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

            new_json = json.dumps(
                zha_device.get_diagnostics_json(), indent=2, cls=ZhaJsonEncoder
            )
            device_json.write_text(new_json)


if __name__ == "__main__":
    asyncio.run(main())
