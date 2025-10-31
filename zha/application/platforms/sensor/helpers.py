"""Helpers for sensor platform."""

import functools
from math import ceil, log10

from zigpy.zcl.clusters.smartenergy import NumberFormatting


def resolution_to_decimal_precision(
    resolution: float, *, epsilon: float = 2**-23, max_digits: int = 16
) -> int:
    """Calculate the decimal precision for the provided resolution."""
    assert resolution > 0

    threshold = epsilon * max(abs(resolution), 1.0)

    # If the resolution can be closely represented by a fraction n/10^d for some d, we
    # can assume that this is what was intended as the "real" resolution that was then
    # modified during float32 conversion
    for d in range(0, max_digits):
        k = 10**d
        n = round(resolution * k)

        if n == 0:
            continue

        # `abs(resolution - n / k) <= threshold` with less division
        if abs(resolution * k - n) <= threshold * k:
            return d

    # If nothing was found, fall back to the number of decimal places in epsilon
    return ceil(-log10(epsilon))


@functools.lru_cache(maxsize=32)
def create_number_formatter(formatting: int) -> str:
    """Return a formatting string, given the formatting value."""
    formatting_obj = NumberFormatting(formatting)
    r_digits = formatting_obj.num_digits_right_of_decimal
    l_digits = formatting_obj.num_digits_left_of_decimal

    if l_digits == 0:
        l_digits = 15

    width = r_digits + l_digits + (1 if r_digits > 0 else 0)

    if formatting_obj.suppress_leading_zeros:
        # suppress leading 0
        return f"{{:{width}.{r_digits}f}}"

    return f"{{:0{width}.{r_digits}f}}"
