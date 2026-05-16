"""Exceptions for Zigbee Home Automation."""

from collections.abc import Iterator
from contextlib import contextmanager

import zigpy.exceptions


class ZHAException(Exception):
    """Base ZHA exception."""


@contextmanager
def wrap_zigpy_exceptions() -> Iterator[None]:
    """Wrap zigpy exceptions in `ZHAException` exceptions."""
    try:
        yield
    except TimeoutError as exc:
        raise ZHAException("Failed to send request: device did not respond") from exc
    except zigpy.exceptions.ZigbeeException as exc:
        message = "Failed to send request"

        if str(exc):
            message = f"{message}: {exc}"

        raise ZHAException(message) from exc
