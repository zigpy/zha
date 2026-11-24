"""Tests for cluster configuration aggregation."""

from unittest.mock import patch

import pytest
import zigpy.profiles.zha
from zigpy.zcl import ReportingConfig
from zigpy.zcl.clusters import general, homeautomation

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
)
from zha.application.gateway import Gateway
from zha.application.platforms import AttrConfig, ClusterConfig, sensor
from zha.zigbee.cluster_config import AggregatedAttrConfig

# A tight, non-overriding config, like the ones ZHA's built-in entities declare
DEFAULT = ReportingConfig(min_interval=5, max_interval=900, reportable_change=1)
RELAXED = ReportingConfig(min_interval=30, max_interval=3600, reportable_change=100)
RELAXED_TIGHTER = ReportingConfig(
    min_interval=10, max_interval=1800, reportable_change=50
)


def test_merge_tightest_wins_by_default() -> None:
    """Without overrides, the tightest of each reporting field wins."""
    agg = AggregatedAttrConfig()
    agg.merge(AttrConfig(read_on_startup=False, reporting=RELAXED))
    agg.merge(AttrConfig(read_on_startup=True, reporting=DEFAULT))
    assert agg.read_on_startup is True
    assert agg.reporting_override is False
    assert agg.reporting == DEFAULT


def test_merge_override_replaces_defaults() -> None:
    """An overriding config replaces already merged non-overriding configs."""
    agg = AggregatedAttrConfig()
    agg.merge(AttrConfig(read_on_startup=True, reporting=DEFAULT))
    agg.merge(
        AttrConfig(read_on_startup=False, reporting=RELAXED, reporting_override=True)
    )
    assert agg.reporting_override is True
    assert agg.reporting == RELAXED
    # the fresh read is unaffected by the reporting override
    assert agg.read_on_startup is True


def test_merge_override_ignores_later_defaults() -> None:
    """Non-overriding configs merged after an override do not tighten it."""
    agg = AggregatedAttrConfig()
    agg.merge(
        AttrConfig(read_on_startup=False, reporting=RELAXED, reporting_override=True)
    )
    agg.merge(AttrConfig(read_on_startup=False, reporting=DEFAULT))
    assert agg.reporting == RELAXED


def test_merge_multiple_overrides_take_tightest() -> None:
    """Multiple overriding configs are merged with each other."""
    agg = AggregatedAttrConfig()
    agg.merge(AttrConfig(read_on_startup=False, reporting=DEFAULT))
    agg.merge(
        AttrConfig(read_on_startup=False, reporting=RELAXED, reporting_override=True)
    )
    agg.merge(
        AttrConfig(
            read_on_startup=False, reporting=RELAXED_TIGHTER, reporting_override=True
        )
    )
    assert agg.reporting == RELAXED_TIGHTER


def test_override_without_reporting_is_rejected() -> None:
    """An overriding attr config must carry a reporting config."""
    with pytest.raises(ValueError, match="requires a reporting config"):
        AttrConfig(read_on_startup=True, reporting_override=True)


async def test_reporting_override_configures_relaxed_reporting(
    zha_gateway: Gateway,
) -> None:
    """An entity's overriding reporting config replaces the built-in default."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    homeautomation.ElectricalMeasurement.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SMART_PLUG,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
    )
    cluster = zigpy_device.endpoints[1].electrical_measurement
    em_attrs = homeautomation.ElectricalMeasurement.AttributeDefs

    # Simulate a device-specific (e.g. quirk-provided) entity declaring a relaxed
    # reporting config for `rms_voltage`, alongside the built-in voltage entity
    # declaring the default one for the same attribute. Quirks key attributes by
    # name (str) while built-in entities use the ZCLAttributeDef, so both spellings
    # must aggregate to the same attribute.
    override_config = {
        homeautomation.ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                em_attrs.rms_voltage.name: AttrConfig(
                    read_on_startup=False,
                    reporting=RELAXED,
                    reporting_override=True,
                ),
            },
        )
    }
    with patch.object(
        sensor.ElectricalMeasurementRMSCurrent,
        "_server_cluster_config",
        override_config,
    ):
        await join_zigpy_device(zha_gateway, zigpy_device)

    assert len(cluster.configure_reporting_multiple.mock_calls) == 1
    configured = cluster.configure_reporting_multiple.mock_calls[0].args[0]
    assert configured[em_attrs.rms_voltage] == RELAXED
    # Attributes without an override keep the built-in default
    assert configured[em_attrs.active_power] == DEFAULT
