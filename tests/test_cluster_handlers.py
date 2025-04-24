"""Test ZHA Core cluster_handlers."""

# pylint:disable=redefined-outer-name,too-many-lines

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from zhaquirks.centralite.cl_3130 import CentraLite3130
from zhaquirks.xiaomi.aqara.sensor_switch_aq3 import BUTTON_DEVICE_TYPE, SwitchAQ3
from zigpy.device import Device as ZigpyDevice
from zigpy.endpoint import Endpoint as ZigpyEndpoint
import zigpy.profiles.zha
from zigpy.quirks import _DEVICE_REGISTRY
import zigpy.types as t
from zigpy.zcl import foundation
import zigpy.zcl.clusters
from zigpy.zcl.clusters import CLUSTERS_BY_ID
from zigpy.zcl.clusters.general import (
    Basic,
    Identify,
    LevelControl,
    MultistateInput,
    OnOff,
    Ota,
    PollControl,
    PowerConfiguration,
)
from zigpy.zcl.clusters.homeautomation import Diagnostic
from zigpy.zcl.clusters.measurement import TemperatureMeasurement
import zigpy.zdo.types as zdo_t

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    make_zcl_header,
    send_attributes_report,
)
from zha.application.const import ATTR_QUIRK_ID
from zha.application.gateway import Gateway
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import (
    AttrReportConfig,
    ClientClusterHandler,
    ClusterHandler,
    ClusterHandlerStatus,
    parse_and_log_command,
    retry_request,
)
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_COLOR,
    CLUSTER_HANDLER_LEVEL,
    CLUSTER_HANDLER_ON_OFF,
)
from zha.zigbee.cluster_handlers.general import PollControlClusterHandler
from zha.zigbee.cluster_handlers.lighting import ColorClusterHandler
from zha.zigbee.cluster_handlers.lightlink import LightLinkClusterHandler
from zha.zigbee.cluster_handlers.registries import (
    CLIENT_CLUSTER_HANDLER_REGISTRY,
    CLUSTER_HANDLER_REGISTRY,
)
from zha.zigbee.device import Device
from zha.zigbee.endpoint import Endpoint


@pytest.fixture
def ieee():
    """IEEE fixture."""
    return t.EUI64.deserialize(b"ieeeaddr")[0]


@pytest.fixture
def nwk():
    """NWK fixture."""
    return t.NWK(0xBEEF)


def zigpy_coordinator_device_mock(zha_gateway: Gateway) -> ZigpyDevice:
    """Coordinator device fixture."""

    coordinator = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [0x1000],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
        nwk=0x0000,
    )
    coordinator.add_to_group = AsyncMock(return_value=[0])
    return coordinator


def endpoint_mock(zigpy_coordinator_device: ZigpyDevice) -> Endpoint:
    """Endpoint cluster_handlers fixture."""
    endpoint_mock = mock.MagicMock(spec_set=Endpoint)
    endpoint_mock.zigpy_endpoint.device.application.get_device.return_value = (
        zigpy_coordinator_device
    )
    endpoint_mock.device.skip_configuration = False
    endpoint_mock.id = 1
    return endpoint_mock


def poll_control_ch_mock(
    endpoint: Endpoint,
    zha_gateway: Gateway,
) -> PollControlClusterHandler:
    """Poll control cluster_handler fixture."""
    cluster_id = zigpy.zcl.clusters.general.PollControl.cluster_id
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].in_clusters[cluster_id]
    cluster_handler_class: type[PollControlClusterHandler] | None = (
        CLUSTER_HANDLER_REGISTRY.get(cluster_id).get(None)
    )
    assert cluster_handler_class is not None

    return cluster_handler_class(cluster, endpoint)


async def poll_control_device_mock(zha_gateway: Gateway) -> Device:
    """Poll control device fixture."""
    cluster_id = zigpy.zcl.clusters.general.PollControl.cluster_id
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)
    return zha_device


@pytest.mark.parametrize(
    ("cluster_id", "bind_count", "attrs"),
    [
        (zigpy.zcl.clusters.general.Basic.cluster_id, 0, set()),
        (
            zigpy.zcl.clusters.general.PowerConfiguration.cluster_id,
            1,
            {"battery_voltage", "battery_percentage_remaining"},
        ),
        (
            zigpy.zcl.clusters.general.DeviceTemperature.cluster_id,
            1,
            {"current_temperature"},
        ),
        (zigpy.zcl.clusters.general.Identify.cluster_id, 0, set()),
        (zigpy.zcl.clusters.general.Groups.cluster_id, 0, set()),
        (zigpy.zcl.clusters.general.Scenes.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.OnOff.cluster_id, 1, {"on_off"}),
        (zigpy.zcl.clusters.general.OnOffConfiguration.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.LevelControl.cluster_id, 1, {"current_level"}),
        (zigpy.zcl.clusters.general.Alarms.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.AnalogInput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.AnalogOutput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.AnalogValue.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.AnalogOutput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.BinaryOutput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.BinaryValue.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.MultistateInput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.MultistateOutput.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.MultistateValue.cluster_id, 1, {"present_value"}),
        (zigpy.zcl.clusters.general.Commissioning.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.Partition.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.Ota.cluster_id, 0, set()),
        (zigpy.zcl.clusters.general.PowerProfile.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.ApplianceControl.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.PollControl.cluster_id, 1, set()),
        (zigpy.zcl.clusters.general.GreenPowerProxy.cluster_id, 0, set()),
        (zigpy.zcl.clusters.closures.DoorLock.cluster_id, 1, {"lock_state"}),
        (
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            1,
            {
                "local_temperature",
                "occupied_cooling_setpoint",
                "occupied_heating_setpoint",
                "unoccupied_cooling_setpoint",
                "unoccupied_heating_setpoint",
                "running_mode",
                "running_state",
                "system_mode",
                "occupancy",
                "pi_cooling_demand",
                "pi_heating_demand",
            },
        ),
        (zigpy.zcl.clusters.hvac.Fan.cluster_id, 1, {"fan_mode"}),
        (
            zigpy.zcl.clusters.lighting.Color.cluster_id,
            1,
            {
                "current_x",
                "current_y",
                "color_temperature",
            },
        ),
        (
            zigpy.zcl.clusters.measurement.IlluminanceMeasurement.cluster_id,
            1,
            {"measured_value"},
        ),
        (
            zigpy.zcl.clusters.measurement.IlluminanceLevelSensing.cluster_id,
            1,
            {"level_status"},
        ),
        (
            zigpy.zcl.clusters.measurement.TemperatureMeasurement.cluster_id,
            1,
            {"measured_value"},
        ),
        (
            zigpy.zcl.clusters.measurement.PressureMeasurement.cluster_id,
            1,
            {"measured_value"},
        ),
        (
            zigpy.zcl.clusters.measurement.FlowMeasurement.cluster_id,
            1,
            {"measured_value"},
        ),
        (
            zigpy.zcl.clusters.measurement.RelativeHumidity.cluster_id,
            1,
            {"measured_value"},
        ),
        (zigpy.zcl.clusters.measurement.OccupancySensing.cluster_id, 1, {"occupancy"}),
        (
            zigpy.zcl.clusters.smartenergy.Metering.cluster_id,
            1,
            {
                "instantaneous_demand",
                "current_summ_delivered",
                "current_tier1_summ_delivered",
                "current_tier2_summ_delivered",
                "current_tier3_summ_delivered",
                "current_tier4_summ_delivered",
                "current_tier5_summ_delivered",
                "current_tier6_summ_delivered",
                "current_summ_received",
                "status",
            },
        ),
        (
            zigpy.zcl.clusters.homeautomation.ElectricalMeasurement.cluster_id,
            1,
            {
                "ac_frequency",
                "ac_voltage_divisor",
                "ac_current_divisor",
                "ac_power_divisor",
                "ac_voltage_multiplier",
                "ac_power_multiplier",
                "power_divisor",
                "power_multiplier",
                "ac_current_multiplier",
                "ac_frequency",
                "active_power",
                "active_power_ph_b",
                "active_power_ph_c",
                "apparent_power",
                "rms_current",
                "rms_current_ph_b",
                "rms_current_ph_c",
                "rms_voltage",
                "rms_voltage_ph_b",
                "rms_voltage_ph_c",
            },
        ),
    ],
)
async def test_in_cluster_handler_config(
    cluster_id, bind_count, attrs, zha_gateway: Gateway
) -> None:
    """Test ZHA core cluster handler configuration for input clusters."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].in_clusters[cluster_id]
    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    assert cluster_handler.status == ClusterHandlerStatus.CREATED

    if TYPE_CHECKING:
        # Workaround for https://github.com/python/mypy/issues/9005
        assert cluster_handler.status != ClusterHandlerStatus.CREATED

    await cluster_handler.async_configure()

    assert cluster_handler.status == ClusterHandlerStatus.CONFIGURED

    assert cluster.bind.call_count == bind_count

    reported_attrs = set()

    for mock_call in cluster.configure_reporting_multiple.mock_calls:
        reported_attrs.update(mock_call.args[0].keys())

    assert attrs == reported_attrs
    assert cluster.configure_reporting.call_count == 0
    assert cluster.configure_reporting_multiple.call_count == math.ceil(len(attrs) / 3)


async def test_cluster_handler_bind_error(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA core cluster handler bind error."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [OnOff.cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster: zigpy.zcl.Cluster = zigpy_dev.endpoints[1].in_clusters[OnOff.cluster_id]
    cluster.bind.side_effect = zigpy.exceptions.ZigbeeException

    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        OnOff.cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.async_configure()

    assert cluster.bind.await_count == 1
    assert cluster.configure_reporting.await_count == 0
    assert f"Failed to bind '{cluster.ep_attribute}' cluster:" in caplog.text


async def test_cluster_handler_configure_reporting_error(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA core cluster handler configure reporting error."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [OnOff.cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster: zigpy.zcl.Cluster = zigpy_dev.endpoints[1].in_clusters[OnOff.cluster_id]
    cluster.configure_reporting_multiple.side_effect = zigpy.exceptions.ZigbeeException

    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        OnOff.cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.async_configure()

    assert cluster.bind.await_count == 1
    assert cluster.configure_reporting_multiple.await_count == 1
    assert f"failed to set reporting on '{cluster.ep_attribute}' cluster" in caplog.text


async def test_write_attributes_safe_key_error(zha_gateway: Gateway) -> None:
    """Test ZHA core cluster handler write attributes safe key error."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [OnOff.cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster: zigpy.zcl.Cluster = zigpy_dev.endpoints[1].in_clusters[OnOff.cluster_id]
    cluster.write_attributes = AsyncMock(
        return_value=[
            foundation.WriteAttributesResponse.deserialize(b"\x01\x00\x00")[0]
        ]
    )

    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        OnOff.cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    with pytest.raises(ZHAException, match="Failed to write attribute on_off=bar"):
        await cluster_handler.write_attributes_safe(
            {OnOff.AttributeDefs.on_off.name: "bar"}
        )


async def test_get_attributes_error(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA core cluster handler get attributes timeout error."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [OnOff.cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster: zigpy.zcl.Cluster = zigpy_dev.endpoints[1].in_clusters[OnOff.cluster_id]
    cluster.read_attributes.side_effect = zigpy.exceptions.ZigbeeException

    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        OnOff.cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.get_attributes(["foo"])

    assert (
        f"failed to get attributes '['foo']' on '{OnOff.ep_attribute}' cluster"
        in caplog.text
    )


async def test_get_attributes_error_raises(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA core cluster handler get attributes timeout error."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [OnOff.cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster: zigpy.zcl.Cluster = zigpy_dev.endpoints[1].in_clusters[OnOff.cluster_id]
    cluster.read_attributes.side_effect = zigpy.exceptions.ZigbeeException

    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        OnOff.cluster_id, {None, ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    with pytest.raises(zigpy.exceptions.ZigbeeException):
        await cluster_handler._get_attributes(True, ["foo"])

    assert (
        f"failed to get attributes '['foo']' on '{OnOff.ep_attribute}' cluster"
        in caplog.text
    )


@pytest.mark.parametrize(
    ("cluster_id", "bind_count"),
    [
        (0x0000, 0),
        (0x0001, 1),
        (0x0002, 1),
        (0x0003, 0),
        (0x0004, 0),
        (0x0005, 1),
        (0x0006, 1),
        (0x0007, 1),
        (0x0008, 1),
        (0x0009, 1),
        (0x0015, 1),
        (0x0016, 1),
        (0x0019, 0),
        (0x001A, 1),
        (0x001B, 1),
        (0x0020, 1),
        (0x0021, 0),
        (0x0101, 1),
        (0x0202, 1),
        (0x0300, 1),
        (0x0400, 1),
        (0x0402, 1),
        (0x0403, 1),
        (0x0405, 1),
        (0x0406, 1),
        (0x0702, 1),
        (0x0B04, 1),
    ],
)
async def test_out_cluster_handler_config(
    cluster_id: int,
    bind_count: int,
    zha_gateway: Gateway,
) -> None:
    """Test ZHA core cluster handler configuration for output clusters."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_OUTPUT: [cluster_id], SIG_EP_INPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].out_clusters[cluster_id]
    cluster.bind_only = True
    cluster_handler_class: type[ClusterHandler] | None = CLUSTER_HANDLER_REGISTRY.get(
        cluster_id, {None: ClusterHandler}
    ).get(None)
    assert cluster_handler_class is not None
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.async_configure()

    assert cluster.bind.call_count == bind_count
    assert cluster.configure_reporting.call_count == 0


def test_cluster_handler_registry() -> None:
    """Test ZIGBEE cluster handler Registry."""

    # get all quirk ID from zigpy quirks registry
    cluster_quirk_id_map: dict[int, set[str | None]] = {}
    for cluster_id in CLUSTERS_BY_ID:
        cluster_quirk_id_map[cluster_id] = {None}

    # loop over custom clusters in v2 quirks registry
    for quirks in _DEVICE_REGISTRY.registry_v2.values():
        for quirk_reg_entry in quirks:
            # get standalone adds_metadata and adds_metadata from replaces_metadata
            all_metadata = set(quirk_reg_entry.adds_metadata) | {
                rm.add for rm in quirk_reg_entry.replaces_metadata
            }
            for metadata in all_metadata:
                cluster_quirk_id_map[metadata.cluster.cluster_id] = {None}

    # loop over custom clusters in v1 quirks registry
    for manufacturer in _DEVICE_REGISTRY.registry_v1.values():
        for model_quirk_list in manufacturer.values():
            for quirk in model_quirk_list:
                quirk_id = getattr(quirk, ATTR_QUIRK_ID, None)
                device_description: dict[str, dict[str, Any]] = getattr(
                    quirk, "replacement", None
                ) or getattr(quirk, "signature", None)

                for endpoint in device_description["endpoints"].values():
                    cluster_ids = set()
                    if "input_clusters" in endpoint:
                        cluster_ids.update(endpoint["input_clusters"])
                    if "output_clusters" in endpoint:
                        cluster_ids.update(endpoint["output_clusters"])
                    for cluster_id in cluster_ids:
                        if not isinstance(cluster_id, int):
                            cluster_id = cluster_id.cluster_id
                        if cluster_id not in cluster_quirk_id_map:
                            cluster_quirk_id_map[cluster_id] = {None}
                        cluster_quirk_id_map[cluster_id].add(quirk_id)

    for (
        cluster_id,
        cluster_handler_classes,
    ) in CLUSTER_HANDLER_REGISTRY.items():
        assert isinstance(cluster_id, int)
        assert 0 <= cluster_id <= 0xFFFF
        assert cluster_id in cluster_quirk_id_map
        assert isinstance(cluster_handler_classes, dict)
        for quirk_id, cluster_handler in cluster_handler_classes.items():
            assert quirk_id is None or isinstance(quirk_id, str)
            assert issubclass(cluster_handler, ClusterHandler)
            assert quirk_id in cluster_quirk_id_map[cluster_id]


def test_epch_unclaimed_cluster_handlers(cluster_handler) -> None:
    """Test unclaimed cluster handlers."""

    ch_1 = cluster_handler(CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(CLUSTER_HANDLER_COLOR, 768)

    mock_dev = mock.MagicMock(spec=Device)
    mock_dev.unique_id = "00:11:22:33:44:55:66:77"

    ep_cluster_handlers = Endpoint(mock.MagicMock(spec_set=ZigpyEndpoint), mock_dev)
    all_cluster_handlers = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    with mock.patch.dict(
        ep_cluster_handlers.all_cluster_handlers, all_cluster_handlers, clear=True
    ):
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 in available
        assert ch_2 in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] = ch_2
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 in available
        assert ch_2 not in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_1.id] = ch_1
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 not in available
        assert ch_2 not in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_3.id] = ch_3
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 not in available
        assert ch_2 not in available
        assert ch_3 not in available


def test_epch_claim_cluster_handlers(cluster_handler) -> None:
    """Test cluster handler claiming."""

    ch_1 = cluster_handler(CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(CLUSTER_HANDLER_COLOR, 768)

    mock_dev = mock.MagicMock(spec=Device)
    mock_dev.unique_id = "00:11:22:33:44:55:66:77"

    ep_cluster_handlers = Endpoint(mock.MagicMock(spec_set=ZigpyEndpoint), mock_dev)
    all_cluster_handlers = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    with mock.patch.dict(
        ep_cluster_handlers.all_cluster_handlers, all_cluster_handlers, clear=True
    ):
        assert ch_1.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_2.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_3.id not in ep_cluster_handlers.claimed_cluster_handlers

        ep_cluster_handlers.claim_cluster_handlers([ch_2])
        assert ch_1.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_2.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] is ch_2
        assert ch_3.id not in ep_cluster_handlers.claimed_cluster_handlers

        ep_cluster_handlers.claim_cluster_handlers([ch_3, ch_1])
        assert ch_1.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_1.id] is ch_1
        assert ch_2.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] is ch_2
        assert ch_3.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_3.id] is ch_3
        assert "1:0x0300" in ep_cluster_handlers.claimed_cluster_handlers


@mock.patch("zha.zigbee.endpoint.Endpoint.add_client_cluster_handlers")
@mock.patch(
    "zha.application.discovery.ENDPOINT_PROBE.discover_entities",
    mock.MagicMock(),
)
async def test_ep_cluster_handlers_all_cluster_handlers(
    m1,  # pylint: disable=unused-argument
    zha_gateway: Gateway,
) -> None:
    """Test Endpointcluster_handlers adding all cluster_handlers."""
    zha_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            {
                1: {
                    SIG_EP_INPUT: [0, 1, 6, 8],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: [0, 1, 6, 8, 768],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            },
        ),
    )
    assert "1:0x0000" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0001" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0006" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0008" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0000" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0001" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0006" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0008" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0000" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0001" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0006" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0008" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0000" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0006" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0008" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0300" in zha_device._endpoints[2].all_cluster_handlers


@mock.patch("zha.zigbee.endpoint.Endpoint.add_client_cluster_handlers")
@mock.patch(
    "zha.application.discovery.ENDPOINT_PROBE.discover_entities",
    mock.MagicMock(),
)
async def test_cluster_handler_power_config(
    m1,  # pylint: disable=unused-argument
    zha_gateway: Gateway,
) -> None:
    """Test that cluster_handlers only get a single power cluster_handler."""
    in_clusters = [0, 1, 6, 8]
    zha_device: Device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            endpoints={
                1: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: [*in_clusters, 768],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            },
            ieee="01:2d:6f:00:0a:90:69:e8",
        ),
    )
    assert "1:0x0000" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0001" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0006" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0008" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0000" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0006" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0008" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0300" in zha_device._endpoints[2].all_cluster_handlers

    zha_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            endpoints={
                1: {
                    SIG_EP_INPUT: [],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            },
            ieee="02:2d:6f:00:0a:90:69:e8",
        ),
    )
    assert "1:0x0001" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers

    zha_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            endpoints={
                2: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                }
            },
            ieee="03:2d:6f:00:0a:90:69:e8",
        ),
    )
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers


async def test_ep_cluster_handlers_configure(cluster_handler) -> None:
    """Test unclaimed cluster handlers."""

    ch_1 = cluster_handler(CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(CLUSTER_HANDLER_COLOR, 768)
    ch_3.async_configure = AsyncMock(side_effect=TimeoutError)
    ch_3.async_initialize = AsyncMock(side_effect=TimeoutError)
    ch_4 = cluster_handler(CLUSTER_HANDLER_ON_OFF, 6)
    ch_5 = cluster_handler(CLUSTER_HANDLER_LEVEL, 8)
    ch_5.async_configure = AsyncMock(side_effect=TimeoutError)
    ch_5.async_initialize = AsyncMock(side_effect=TimeoutError)

    endpoint_mock = mock.MagicMock(spec_set=ZigpyEndpoint)
    type(endpoint_mock).in_clusters = mock.PropertyMock(return_value={})
    type(endpoint_mock).out_clusters = mock.PropertyMock(return_value={})
    type(endpoint_mock).profile_id = mock.PropertyMock(
        return_value=zigpy.profiles.zha.PROFILE_ID
    )
    type(endpoint_mock).device_type = mock.PropertyMock(
        return_value=zigpy.profiles.zha.DeviceType.COLOR_DIMMABLE_LIGHT
    )
    zha_dev = mock.MagicMock(spec=Device)
    zha_dev.unique_id = "00:11:22:33:44:55:66:77"
    type(zha_dev).quirk_id = mock.PropertyMock(return_value=None)
    endpoint = Endpoint.new(endpoint_mock, zha_dev)

    claimed = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    client_handlers = {ch_4.id: ch_4, ch_5.id: ch_5}

    with (
        mock.patch.dict(endpoint.claimed_cluster_handlers, claimed, clear=True),
        mock.patch.dict(endpoint.client_cluster_handlers, client_handlers, clear=True),
    ):
        await endpoint.async_configure()
        await endpoint.async_initialize(mock.sentinel.from_cache)

    for ch in [*claimed.values(), *client_handlers.values()]:
        assert ch.async_initialize.call_count == 1
        assert ch.async_initialize.await_count == 1
        assert ch.async_initialize.call_args[0][0] is mock.sentinel.from_cache
        assert ch.async_configure.call_count == 1
        assert ch.async_configure.await_count == 1

    assert ch_3.debug.call_count == 2
    assert ch_5.debug.call_count == 2


async def test_poll_control_configure(zha_gateway: Gateway) -> None:
    """Test poll control cluster_handler configuration."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    poll_control_ch: PollControlClusterHandler = poll_control_ch_mock(
        endpoint, zha_gateway
    )
    await poll_control_ch.async_configure()
    assert poll_control_ch.cluster.write_attributes.call_count == 1
    assert poll_control_ch.cluster.write_attributes.call_args[0][0] == {
        "checkin_interval": poll_control_ch.CHECKIN_INTERVAL
    }


async def test_poll_control_checkin_response(zha_gateway: Gateway) -> None:
    """Test poll control cluster_handler checkin response."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    poll_control_ch: PollControlClusterHandler = poll_control_ch_mock(
        endpoint, zha_gateway
    )
    rsp_mock = AsyncMock()
    set_interval_mock = AsyncMock()
    fast_poll_mock = AsyncMock()
    cluster = poll_control_ch.cluster
    patch_1 = mock.patch.object(cluster, "checkin_response", rsp_mock)
    patch_2 = mock.patch.object(cluster, "set_long_poll_interval", set_interval_mock)
    patch_3 = mock.patch.object(cluster, "fast_poll_stop", fast_poll_mock)

    with patch_1, patch_2, patch_3:
        await poll_control_ch.check_in_response(33)

    assert rsp_mock.call_count == 1
    assert set_interval_mock.call_count == 1
    assert fast_poll_mock.call_count == 1

    await poll_control_ch.check_in_response(33)
    assert cluster.endpoint.request.call_count == 3
    assert cluster.endpoint.request.await_count == 3
    assert cluster.endpoint.request.mock_calls[0].kwargs["sequence"] == 33
    assert cluster.endpoint.request.mock_calls[0].kwargs["cluster"] == 0x0020
    assert cluster.endpoint.request.mock_calls[1].kwargs["cluster"] == 0x0020


async def test_poll_control_cluster_command(zha_gateway: Gateway) -> None:
    """Test poll control cluster_handler response to cluster command."""
    poll_control_device = await poll_control_device_mock(zha_gateway)
    checkin_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster
    # events = async_capture_events("zha_event")

    poll_control_ch.emit_zha_event = MagicMock(wraps=poll_control_ch.emit_zha_event)
    with mock.patch.object(poll_control_ch, "check_in_response", checkin_mock):
        tsn = 22
        hdr = make_zcl_header(0, global_command=False, tsn=tsn)
        cluster.handle_message(
            hdr, [mock.sentinel.args, mock.sentinel.args2, mock.sentinel.args3]
        )
        await poll_control_device.gateway.async_block_till_done()

    assert checkin_mock.call_count == 1
    assert checkin_mock.await_count == 1
    assert checkin_mock.mock_calls == [call(tsn)]

    assert poll_control_ch.emit_zha_event.call_count == 1
    assert poll_control_ch.emit_zha_event.call_args_list[0] == mock.call(
        "checkin", [mock.sentinel.args, mock.sentinel.args2, mock.sentinel.args3]
    )


async def test_poll_control_ignore_list(zha_gateway: Gateway) -> None:
    """Test poll control cluster_handler ignore list."""
    poll_control_device = await poll_control_device_mock(zha_gateway)
    set_long_poll_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster

    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 1

    set_long_poll_mock.reset_mock()
    poll_control_ch.skip_manufacturer_id(4151)
    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 0


async def test_poll_control_ikea(zha_gateway: Gateway) -> None:
    """Test poll control cluster_handler ignore list for ikea."""
    poll_control_device = await poll_control_device_mock(zha_gateway)
    set_long_poll_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster

    delattr(poll_control_device, "manufacturer_code")
    poll_control_device.device.node_desc.manufacturer_code = 4476

    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 0


def zigpy_zll_device_mock(zha_gateway: Gateway) -> ZigpyDevice:
    """ZLL device fixture."""

    return create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [0x1000],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: zigpy.profiles.zll.PROFILE_ID,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )


async def test_zll_device_groups(zha_gateway: Gateway) -> None:
    """Test adding coordinator to ZLL groups."""
    zigpy_zll_device: ZigpyDevice = zigpy_zll_device_mock(zha_gateway)
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)

    cluster = zigpy_zll_device.endpoints[1].lightlink
    cluster_handler = LightLinkClusterHandler(cluster, endpoint)
    get_group_identifiers_rsp = zigpy.zcl.clusters.lightlink.LightLink.commands_by_name[
        "get_group_identifiers_rsp"
    ].schema

    with patch.object(
        cluster,
        "get_group_identifiers",
        AsyncMock(
            return_value=get_group_identifiers_rsp(
                total=0, start_index=0, group_info_records=[]
            )
        ),
    ) as get_group_identifiers:
        await cluster_handler.async_configure()
        assert get_group_identifiers.await_count == 1
        assert cluster.bind.call_count == 0
        assert zigpy_coordinator_device.add_to_group.await_count == 1
        assert zigpy_coordinator_device.add_to_group.await_args[0][0] == 0x0000

    zigpy_coordinator_device.add_to_group.reset_mock()
    group_1 = zigpy.zcl.clusters.lightlink.GroupInfoRecord(0xABCD, 0x00)
    group_2 = zigpy.zcl.clusters.lightlink.GroupInfoRecord(0xAABB, 0x00)
    with patch.object(
        cluster,
        "get_group_identifiers",
        AsyncMock(
            return_value=get_group_identifiers_rsp(
                total=2, start_index=0, group_info_records=[group_1, group_2]
            )
        ),
    ) as get_group_identifiers:
        await cluster_handler.async_configure()
        assert get_group_identifiers.await_count == 1
        assert cluster.bind.call_count == 0
        assert zigpy_coordinator_device.add_to_group.await_count == 2
        assert (
            zigpy_coordinator_device.add_to_group.await_args_list[0][0][0]
            == group_1.group_id
        )
        assert (
            zigpy_coordinator_device.add_to_group.await_args_list[1][0][0]
            == group_2.group_id
        )


@mock.patch(
    "zha.application.discovery.ENDPOINT_PROBE.discover_entities",
    mock.MagicMock(),
)
async def test_cluster_no_ep_attribute(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test cluster handlers for clusters without ep_attribute."""

    zha_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            {
                1: {
                    SIG_EP_INPUT: [0x042E],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x1234,
                    SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
                }
            },
        ),
    )

    assert "1:0x042e" in zha_device._endpoints[1].all_cluster_handlers
    assert zha_device._endpoints[1].all_cluster_handlers["1:0x042e"].name


async def test_configure_reporting(zha_gateway: Gateway) -> None:
    """Test setting up a cluster handler and configuring attribute reporting in two batches."""

    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)

    class TestZigbeeClusterHandler(ClusterHandler):
        """Test cluster handler that requests reporting for four attributes."""

        BIND = True
        REPORT_CONFIG = (
            # By name
            AttrReportConfig(attr="current_x", config=(1, 60, 1)),
            AttrReportConfig(attr="current_hue", config=(1, 60, 2)),
            AttrReportConfig(attr="color_temperature", config=(1, 60, 3)),
            AttrReportConfig(attr="current_y", config=(1, 60, 4)),
        )

    mock_ep = mock.AsyncMock()
    mock_ep.profile_id = zigpy.profiles.zha.PROFILE_ID
    mock_ep.device.zdo = AsyncMock()

    cluster = zigpy.zcl.clusters.lighting.Color(mock_ep)
    cluster.bind = AsyncMock(
        spec_set=cluster.bind,
        return_value=[zdo_t.Status.SUCCESS],  # ZDOCmd.Bind_rsp
    )
    cluster.configure_reporting_multiple = AsyncMock(
        spec_set=cluster.configure_reporting_multiple,
        return_value=[
            foundation.ConfigureReportingResponseRecord(
                status=foundation.Status.SUCCESS
            )
        ],
    )

    cluster_handler = TestZigbeeClusterHandler(cluster, endpoint)
    await cluster_handler.async_configure()

    # Since we request reporting for five attributes, we need to make two calls (3 + 1)
    assert cluster.configure_reporting_multiple.mock_calls == [
        mock.call(
            {
                "current_x": (1, 60, 1),
                "current_hue": (1, 60, 2),
                "color_temperature": (1, 60, 3),
            }
        ),
        mock.call(
            {
                "current_y": (1, 60, 4),
            }
        ),
    ]


async def test_invalid_cluster_handler(zha_gateway: Gateway, caplog) -> None:  # pylint: disable=unused-argument
    """Test setting up a cluster handler that fails to match properly."""

    class TestZigbeeClusterHandler(ClusterHandler):
        """Test cluster handler that fails to match properly."""

        REPORT_CONFIG = (AttrReportConfig(attr="missing_attr", config=(1, 60, 1)),)

    mock_device = mock.AsyncMock(spec_set=zigpy.device.Device)
    zigpy_ep = zigpy.endpoint.Endpoint(mock_device, endpoint_id=1)
    zigpy_ep.profile_id = zigpy.profiles.zha.PROFILE_ID

    cluster = zigpy_ep.add_input_cluster(zigpy.zcl.clusters.lighting.Color.cluster_id)
    cluster.configure_reporting_multiple = AsyncMock(
        spec_set=cluster.configure_reporting_multiple,
        return_value=[
            foundation.ConfigureReportingResponseRecord(
                status=foundation.Status.SUCCESS
            )
        ],
    )

    mock_zha_device = mock.AsyncMock(spec=Device)
    mock_zha_device.quirk_id = None
    mock_zha_device.unique_id = "aa:bb:cc:dd:11:22:33:44"

    zha_endpoint = Endpoint(zigpy_ep, mock_zha_device)

    # The cluster handler throws an error when matching this cluster
    with pytest.raises(KeyError):
        TestZigbeeClusterHandler(cluster, zha_endpoint)

    # And one is also logged at runtime
    with (
        patch.dict(
            CLUSTER_HANDLER_REGISTRY[cluster.cluster_id],
            {None: TestZigbeeClusterHandler},
        ),
        caplog.at_level(logging.WARNING),
    ):
        zha_endpoint.add_all_cluster_handlers()

    assert "missing_attr" in caplog.text


async def test_standard_cluster_handler(
    zha_gateway: Gateway,
) -> None:  # pylint: disable=unused-argument
    """Test setting up a cluster handler that matches a standard cluster."""

    class TestZigbeeClusterHandler(ColorClusterHandler):
        """Test cluster handler that matches a standard cluster."""

    mock_device = mock.AsyncMock(spec_set=zigpy.device.Device)
    zigpy_ep = zigpy.endpoint.Endpoint(mock_device, endpoint_id=1)
    zigpy_ep.profile_id = zigpy.profiles.zha.PROFILE_ID

    cluster = zigpy_ep.add_input_cluster(zigpy.zcl.clusters.lighting.Color.cluster_id)
    cluster.configure_reporting_multiple = AsyncMock(
        spec_set=cluster.configure_reporting_multiple,
        return_value=[
            foundation.ConfigureReportingResponseRecord(
                status=foundation.Status.SUCCESS
            )
        ],
    )

    mock_zha_device = mock.AsyncMock(spec=Device)
    mock_zha_device.quirk_id = None
    mock_zha_device.unique_id = "aa:bb:cc:dd:11:22:33:44"

    zha_endpoint = Endpoint(zigpy_ep, mock_zha_device)

    with patch.dict(
        CLUSTER_HANDLER_REGISTRY[cluster.cluster_id],
        {"__test_quirk_id": TestZigbeeClusterHandler},
    ):
        zha_endpoint.add_all_cluster_handlers()

    assert len(zha_endpoint.all_cluster_handlers) == 1
    assert isinstance(
        list(zha_endpoint.all_cluster_handlers.values())[0], ColorClusterHandler
    )


async def test_quirk_id_cluster_handler(
    zha_gateway: Gateway,
) -> None:  # pylint: disable=unused-argument
    """Test setting up a cluster handler that matches a standard cluster."""

    class TestZigbeeClusterHandler(ColorClusterHandler):
        """Test cluster handler that matches a standard cluster."""

    mock_device = mock.AsyncMock(spec_set=zigpy.device.Device)
    zigpy_ep = zigpy.endpoint.Endpoint(mock_device, endpoint_id=1)
    zigpy_ep.profile_id = zigpy.profiles.zha.PROFILE_ID

    cluster = zigpy_ep.add_input_cluster(zigpy.zcl.clusters.lighting.Color.cluster_id)
    cluster.configure_reporting_multiple = AsyncMock(
        spec_set=cluster.configure_reporting_multiple,
        return_value=[
            foundation.ConfigureReportingResponseRecord(
                status=foundation.Status.SUCCESS
            )
        ],
    )

    mock_zha_device = mock.AsyncMock(spec=Device)
    mock_zha_device.unique_id = "aa:bb:cc:dd:11:22:33:44"
    mock_zha_device.quirk_id = "__test_quirk_id"
    zha_endpoint = Endpoint(zigpy_ep, mock_zha_device)

    with patch.dict(
        CLUSTER_HANDLER_REGISTRY[cluster.cluster_id],
        {"__test_quirk_id": TestZigbeeClusterHandler},
    ):
        zha_endpoint.add_all_cluster_handlers()

    assert len(zha_endpoint.all_cluster_handlers) == 1
    assert isinstance(
        list(zha_endpoint.all_cluster_handlers.values())[0], TestZigbeeClusterHandler
    )


# parametrize side effects:
@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (zigpy.exceptions.ZigbeeException(), "Failed to send request"),
        (
            zigpy.exceptions.ZigbeeException("Zigbee exception"),
            "Failed to send request: Zigbee exception",
        ),
        (TimeoutError(), "Failed to send request: device did not respond"),
    ],
)
async def test_retry_request(
    side_effect: Exception, expected_error: str | None
) -> None:
    """Test the `retry_request` decorator's handling of zigpy-internal exceptions."""

    async def func(arg1: int, arg2: int) -> int:
        assert arg1 == 1
        assert arg2 == 2

        raise side_effect

    func = mock.AsyncMock(wraps=func)
    decorated_func = retry_request(func)

    with pytest.raises(ZHAException) as exc:
        await decorated_func(1, arg2=2)

    assert func.await_count == 3
    assert isinstance(exc.value, ZHAException)
    assert str(exc.value) == expected_error


async def test_cluster_handler_naming() -> None:
    """Test that all cluster handlers are named appropriately."""
    for client_cluster_handler in CLIENT_CLUSTER_HANDLER_REGISTRY.values():
        assert issubclass(client_cluster_handler, ClientClusterHandler)
        assert client_cluster_handler.__name__.endswith("ClientClusterHandler")

    for cluster_handler_dict in CLUSTER_HANDLER_REGISTRY.values():
        for cluster_handler in cluster_handler_dict.values():
            assert not issubclass(cluster_handler, ClientClusterHandler)
            assert cluster_handler.__name__.endswith("ClusterHandler")


def test_parse_and_log_command(zha_gateway: Gateway):  # noqa: F811
    """Test that `parse_and_log_command` correctly parses a known command."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    poll_control_ch: PollControlClusterHandler = poll_control_ch_mock(
        endpoint, zha_gateway
    )
    assert parse_and_log_command(poll_control_ch, 0x00, 0x01, []) == "fast_poll_stop"


def test_parse_and_log_command_unknown(zha_gateway: Gateway):  # noqa: F811
    """Test that `parse_and_log_command` correctly parses an unknown command."""
    zigpy_coordinator_device: ZigpyDevice = zigpy_coordinator_device_mock(zha_gateway)
    endpoint: Endpoint = endpoint_mock(zigpy_coordinator_device)
    poll_control_ch: PollControlClusterHandler = poll_control_ch_mock(
        endpoint, zha_gateway
    )
    assert parse_and_log_command(poll_control_ch, 0x00, 0xAB, []) == "0xAB"


async def test_zha_send_event_from_quirk(zha_gateway: Gateway):
    """Test that a quirk can send an event."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    Basic.cluster_id,
                    PowerConfiguration.cluster_id,
                    OnOff.cluster_id,
                    MultistateInput.cluster_id,
                ],
                SIG_EP_OUTPUT: [Basic.cluster_id],
                SIG_EP_TYPE: BUTTON_DEVICE_TYPE,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        model="lumi.sensor_switch.aq3",
        manufacturer="LUMI",
        quirk=SwitchAQ3,
    )

    assert isinstance(zigpy_device, SwitchAQ3)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    ms_input_ch = zha_device.endpoints[1].all_cluster_handlers["1:0x0012"]
    assert ms_input_ch is not None

    ms_input_ch.zha_send_event = MagicMock(wraps=ms_input_ch.zha_send_event)

    await send_attributes_report(zha_gateway, ms_input_ch.cluster, {0x0055: 0x01})

    assert ms_input_ch.zha_send_event.call_count == 1
    assert ms_input_ch.zha_send_event.mock_calls == [
        call(
            "single",
            {
                "value": 1.0,
            },
        )
    ]

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    Basic.cluster_id,
                    PowerConfiguration.cluster_id,
                    Identify.cluster_id,
                    PollControl.cluster_id,
                    TemperatureMeasurement.cluster_id,
                    Diagnostic.cluster_id,
                ],
                SIG_EP_OUTPUT: [
                    Identify.cluster_id,
                    OnOff.cluster_id,
                    LevelControl.cluster_id,
                    Ota.cluster_id,
                ],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROL_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        model="LIGHTIFY Dimming Switch",
        manufacturer="OSRAM",
        quirk=CentraLite3130,
        ieee="00:15:8e:01:01:02:03:04",
    )

    assert isinstance(zigpy_device, CentraLite3130)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    on_off_ch = zha_device.endpoints[1].client_cluster_handlers["1:0x0006_client"]
    assert on_off_ch is not None

    on_off_ch.emit_zha_event = MagicMock(wraps=on_off_ch.emit_zha_event)
    on_off_ch.emit_zha_event.reset_mock()

    on_off_ch.cluster_command(1, OnOff.ServerCommandDefs.on.id, [])

    assert on_off_ch.emit_zha_event.call_count == 1
    assert on_off_ch.emit_zha_event.mock_calls == [call("on", [])]
    on_off_ch.emit_zha_event.reset_mock()

    await send_attributes_report(
        zha_gateway, on_off_ch.cluster, {OnOff.AttributeDefs.on_off.name: 0x01}
    )

    assert on_off_ch.emit_zha_event.call_count == 1
    assert on_off_ch.emit_zha_event.mock_calls == [
        call(
            "attribute_updated",
            {
                "attribute_id": 0,
                "attribute_name": "on_off",
                "attribute_value": True,
                "value": True,
            },
        )
    ]

    on_off_ch.emit_zha_event.reset_mock()

    await send_attributes_report(zha_gateway, on_off_ch.cluster, {0x25: "Bar"})

    assert on_off_ch.emit_zha_event.call_count == 1
    assert on_off_ch.emit_zha_event.mock_calls == [
        call(
            "attribute_updated",
            {
                "attribute_id": 0x25,
                "attribute_name": "Unknown",
                "attribute_value": "Bar",
                "value": "Bar",
            },
        )
    ]


async def test_zdo_cluster_handler(zha_gateway: Gateway):
    """Test that a quirk can send an event."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    Basic.cluster_id,
                    PowerConfiguration.cluster_id,
                    OnOff.cluster_id,
                    MultistateInput.cluster_id,
                ],
                SIG_EP_OUTPUT: [Basic.cluster_id],
                SIG_EP_TYPE: BUTTON_DEVICE_TYPE,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        model="lumi.sensor_switch.aq3",
        manufacturer="LUMI",
        quirk=SwitchAQ3,
    )

    assert isinstance(zigpy_device, SwitchAQ3)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert zha_device.zdo_cluster_handler is not None
    assert zha_device.zdo_cluster_handler.status == ClusterHandlerStatus.INITIALIZED
    assert zha_device.zdo_cluster_handler.cluster is not None
    assert zha_device.zdo_cluster_handler.cluster == zigpy_device.endpoints[0]
    assert (
        zha_device.zdo_cluster_handler.unique_id
        == f"{str(zha_device.ieee)}:{zha_device.name}_ZDO"
    )
