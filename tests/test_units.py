"""Tests for units."""

import enum

import pytest
from zigpy.quirks.v2.homeassistant import UnitOfPower as QuirksUnitOfPower

from zha.units import UnitOfPower, validate_unit


def test_unit_validation() -> None:
    """Test unit validation."""

    assert validate_unit(QuirksUnitOfPower.WATT) == UnitOfPower.WATT

    class FooUnit(enum.Enum):
        """Foo unit."""

        BAR = "bar"

    class UnitOfMass(enum.Enum):
        """UnitOfMass."""

        BAR = "bar"

    with pytest.raises(KeyError):
        validate_unit(FooUnit.BAR)

    with pytest.raises(ValueError):
        validate_unit(UnitOfMass.BAR)
