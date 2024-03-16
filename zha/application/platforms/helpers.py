"""Entity helpers for the zhaws server."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any


def find_state_attributes(states: list[dict], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        if (value := state.get(key)) is not None:
            yield value


def mean_int(*args: Any) -> int:
    """Return the mean of the supplied values."""
    return int(sum(args) / len(args))


def mean_tuple(*args: Any) -> tuple:
    """Return the mean values along the columns of the supplied values."""
    return tuple(sum(x) / len(x) for x in zip(*args))


def reduce_attribute(
    states: list[dict],
    key: str,
    default: Any | None = None,
    reduce: Callable[..., Any] = mean_int,
) -> Any:
    """Find the first attribute matching key from states.

    If none are found, return default.
    """
    attrs = list(find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)
