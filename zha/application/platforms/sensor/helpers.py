"""Helpers for sensor platform."""

from math import ceil, log10


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
