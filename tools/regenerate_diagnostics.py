"""Regenerate device diagnostics JSON, when new entities are added."""

import sys

sys.path.insert(0, "tests")

import asyncio
import contextlib
import json
import logging
import pathlib
from unittest.mock import patch

from tests.common import ZhaJsonEncoder, join_zigpy_device, zigpy_device_from_json
from tests.conftest import TestGateway, make_zha_data, make_zigpy_app_controller

REPO_ROOT = pathlib.Path(__file__).parent.parent
_LOGGER = logging.getLogger(__name__)


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


async def main(files: list[str] | None = None) -> None:
    """Entry point."""
    if files is None:
        paths = list((REPO_ROOT / "tests" / "data" / "devices").glob("**/*.json"))
    else:
        paths = [pathlib.Path(f) for f in files]

    async with create_zha_gateway() as zha_gateway:
        for device_json in paths:
            _LOGGER.info("Migrating %s", device_json)
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

            await zha_device.on_remove()


if __name__ == "__main__":
    import coloredlogs

    coloredlogs.install(level="DEBUG")

    asyncio.run(
        main(
            files=(sys.argv[1:] if len(sys.argv) > 1 else None),
        )
    )
