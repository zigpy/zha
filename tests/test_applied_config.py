"""Tests for the records of applied device configuration."""

import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from zhaquirks import LocalDataCluster
import zigpy.exceptions
import zigpy.profiles.zha
from zigpy.zcl import ReportingConfig
from zigpy.zcl.clusters import general
import zigpy.zcl.foundation as zcl_f
from zigpy.zcl.foundation import ZCLAttributeDef
import zigpy.zdo.types as zdo_t

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    ZhaJsonEncoder,
    create_mock_zigpy_device,
    get_fixture_diagnostics_json,
    join_zigpy_device,
)
from zha.application import Platform
from zha.application.const import ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT
from zha.application.gateway import Gateway
from zha.application.platforms import light
from zha.zigbee.applied_config import (
    APPLIED_CONFIG_NAMESPACE,
    AppliedConfigRecorder,
    ConfigResult,
    binding_key,
    reporting_key,
)
from zha.zigbee.cluster_config import (
    AggregatedAttrConfig,
    AggregatedClusterConfig,
    configure_cluster_configs,
)
from zha.zigbee.device import ClusterBinding, Device, ZigbeeDevice
from zha.zigbee.store import store_key

LIGHT_IEEE = "01:2d:6f:00:0a:90:69:e8"
REMOTE_IEEE = "02:2d:6f:00:0a:90:69:e8"
COORDINATOR_IEEE = "00:15:8d:00:02:32:4f:32"

DEFAULT = ReportingConfig(min_interval=0, max_interval=900, reportable_change=1)


def coordinator_destination(endpoint: int = 1) -> zdo_t.MultiAddress:
    """Return the destination of a binding to the test coordinator."""
    return zdo_t.MultiAddress(
        addrmode=3,
        ieee=zigpy.types.EUI64.convert(COORDINATOR_IEEE),
        endpoint=endpoint,
    )


def records(zha_device: Device) -> dict:
    """Return the device's applied-config records."""
    namespace = zha_device.device.store.namespace(APPLIED_CONFIG_NAMESPACE)
    return {key: namespace[key] for key in namespace}


async def join_light(zha_gateway: Gateway) -> ZigbeeDevice:
    """Join a dimmable light, which ZHA binds and configures reporting for."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee=LIGHT_IEEE,
        nwk=0x1234,
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    assert isinstance(zha_device, ZigbeeDevice)
    return zha_device


async def join_remote(zha_gateway: Gateway) -> ZigbeeDevice:
    """Join a remote with bindable On/Off and Level Control output clusters."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                ],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.REMOTE_CONTROL,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee=REMOTE_IEEE,
        nwk=0x2345,
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    assert isinstance(zha_device, ZigbeeDevice)
    return zha_device


def test_store_key() -> None:
    """Keys are built from parts, which cannot contain the separator."""
    assert store_key("binding", 1, 6, "ieee", COORDINATOR_IEEE, 1) == (
        f"binding/0x0001/0x0006/ieee/{COORDINATOR_IEEE}/0x0001"
    )
    assert store_key("reporting", 1, None) == "reporting/0x0001/-"

    # A prefix of whole parts matches only keys that have those parts
    assert not store_key("binding", 0x10).startswith(store_key("binding", 1) + "/")

    # A string never renders like an integer or `None`
    for part in ("a/b", "", "-", "0x0001", "0x12345"):
        with pytest.raises(ValueError):
            store_key("binding", part)

    # Strings an integer never renders as are fine
    assert store_key("binding", "0x1", "0X0001") == "binding/0x1/0X0001"

    with pytest.raises(TypeError):
        store_key("binding", True)

    assert store_key("binding", 0x12345) == "binding/0x12345"

    with pytest.raises(ValueError):
        store_key("binding", -1)

    with pytest.raises(ValueError):
        store_key()


def test_config_result() -> None:
    """Statuses are kept by name, exceptions by class."""
    assert ConfigResult.from_status(0) == ConfigResult(status="SUCCESS")
    assert ConfigResult.from_status(zdo_t.Status.TABLE_FULL) == ConfigResult(
        status="TABLE_FULL"
    )
    assert ConfigResult.from_status(zcl_f.Status.UNSUPPORTED_ATTRIBUTE) == (
        ConfigResult(status="UNSUPPORTED_ATTRIBUTE")
    )
    assert ConfigResult.from_status(0x7F) == ConfigResult(status="undefined_0x7f")
    assert ConfigResult.from_exception(TimeoutError()) == ConfigResult(
        error="TimeoutError"
    )

    no_entry = ConfigResult(status="NO_ENTRY")
    assert no_entry.is_acknowledged("unbind")
    assert not no_entry.is_acknowledged("bind")
    assert not ConfigResult(error="TimeoutError").is_acknowledged()


async def test_configure_records_bindings_and_reporting(
    zha_gateway: Gateway,
) -> None:
    """Configuring a device records each binding and reporting configuration."""
    zha_device = await join_light(zha_gateway)
    stored = records(zha_device)

    on_off_binding = stored[binding_key(1, 6, coordinator_destination())]
    assert on_off_binding == {
        "kind": "binding",
        "endpoint": 1,
        "cluster_id": 6,
        "destination": {"ieee": COORDINATOR_IEEE, "endpoint": 1, "coordinator": True},
        "desired_by": {"zha": {"sides": ["server"]}},
        "last_attempt": {
            "time": on_off_binding["last_attempt"]["time"],
            "operation": "bind",
            "origin": "zha",
            "status": "SUCCESS",
        },
        "acknowledged": {
            "bound": True,
            "time": on_off_binding["last_attempt"]["time"],
        },
    }
    assert binding_key(1, 8, coordinator_destination()) in stored

    on_off_reporting = stored[reporting_key(1, True, 6, 0x0000, None)]
    assert on_off_reporting == {
        "kind": "reporting",
        "endpoint": 1,
        "side": "server",
        "cluster_id": 6,
        "attribute_id": 0x0000,
        "attribute": "on_off",
        "manufacturer_code": None,
        "desired_by": {"zha": {"min": 0, "max": 900, "change": 1}},
        "last_attempt": {
            "time": on_off_reporting["last_attempt"]["time"],
            "status": "SUCCESS",
        },
        "acknowledged": {
            "min": 0,
            "max": 900,
            "change": 1,
            "time": on_off_reporting["last_attempt"]["time"],
        },
    }

    # Records are versioned like any stored value
    namespace = zha_device.device.store.namespace(APPLIED_CONFIG_NAMESPACE)
    assert {item.version for _key, item in namespace.items()} == {1}


async def test_configure_records_bind_failures(zha_gateway: Gateway) -> None:
    """A bind answered with a failure, or not answered, keeps the earlier ack."""
    zha_device = await join_light(zha_gateway)
    on_off = zha_device.device.endpoints[1].on_off
    level = zha_device.device.endpoints[1].level
    on_off_key = binding_key(1, 6, coordinator_destination())
    level_key = binding_key(1, 8, coordinator_destination())
    acknowledged = records(zha_device)[on_off_key]["acknowledged"]

    on_off.bind = AsyncMock(return_value=[zdo_t.Status.TABLE_FULL])
    level.bind = AsyncMock(side_effect=zigpy.exceptions.DeliveryError("failed"))
    await zha_device.async_configure()

    stored = records(zha_device)
    assert stored[on_off_key]["last_attempt"]["status"] == "TABLE_FULL"
    assert "error" not in stored[on_off_key]["last_attempt"]
    assert stored[on_off_key]["acknowledged"] == acknowledged
    assert stored[level_key]["last_attempt"]["error"] == "DeliveryError"
    assert "status" not in stored[level_key]["last_attempt"]

    level.bind = AsyncMock(side_effect=TimeoutError())
    await zha_device.async_configure()
    assert records(zha_device)[level_key]["last_attempt"]["error"] == "TimeoutError"


async def test_configure_records_reporting_statuses(zha_gateway: Gateway) -> None:
    """Per-attribute statuses are kept apart from a request that failed as a whole."""
    zha_device = await join_light(zha_gateway)
    on_off = zha_device.device.endpoints[1].on_off
    level = zha_device.device.endpoints[1].level
    on_off_key = reporting_key(1, True, 6, 0x0000, None)
    level_key = reporting_key(1, True, 8, 0x0000, None)
    acknowledged = records(zha_device)[level_key]["acknowledged"]

    on_off.configure_reporting_multiple = AsyncMock(
        side_effect=lambda config: dict.fromkeys(
            config, zcl_f.Status.UNREPORTABLE_ATTRIBUTE
        )
    )
    level.configure_reporting_multiple = AsyncMock(side_effect=TimeoutError())
    await zha_device.async_configure()

    stored = records(zha_device)
    assert stored[on_off_key]["last_attempt"]["status"] == "UNREPORTABLE_ATTRIBUTE"
    assert stored[level_key]["last_attempt"]["error"] == "TimeoutError"
    assert stored[level_key]["acknowledged"] == acknowledged

    # A response without a status for an attribute
    level.configure_reporting_multiple = AsyncMock(return_value={})
    await zha_device.async_configure()
    assert records(zha_device)[level_key]["last_attempt"]["error"] == "NoStatus"


async def test_configure_reporting_partial_failure(zha_gateway: Gateway) -> None:
    """Attributes configured before a later request raised are not marked failed.

    zigpy sends one request per manufacturer code.
    """
    zha_device = await join_light(zha_gateway)
    level = zha_device.device.endpoints[1].level
    attrs = general.LevelControl.AttributeDefs

    # Use zigpy's own implementation instead of the test double
    del level.configure_reporting_multiple
    manufacturer_codes = {attrs.current_level.id: None, attrs.on_level.id: 0x1234}

    with patch.object(
        level,
        "_get_effective_manufacturer_code",
        side_effect=lambda attr_def, *args: manufacturer_codes[attr_def.id],
    ):
        level._configure_reporting = AsyncMock(
            side_effect=[
                [[zcl_f.ConfigureReportingResponseRecord(status=zcl_f.Status.SUCCESS)]],
                TimeoutError(),
            ]
        )

        events = []
        zha_device.on_event(ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT, events.append)

        await configure_cluster_configs(
            zha_device,
            {
                (1, 8, True): AggregatedClusterConfig(
                    cluster=level,
                    attributes={
                        attrs.current_level.name: AggregatedAttrConfig(
                            reporting=DEFAULT
                        ),
                        attrs.on_level.name: AggregatedAttrConfig(reporting=DEFAULT),
                    },
                )
            },
        )

    assert len(level._configure_reporting.mock_calls) == 2
    stored = records(zha_device)
    current_level = stored[reporting_key(1, True, 8, attrs.current_level.id, None)]
    on_level = stored[reporting_key(1, True, 8, attrs.on_level.id, 0x1234)]
    assert current_level["last_attempt"]["status"] == "SUCCESS"
    assert on_level["last_attempt"] == {
        "time": on_level["last_attempt"]["time"],
        "error": "TimeoutError",
    }
    assert on_level["manufacturer_code"] == 0x1234
    assert "acknowledged" not in on_level

    statuses = {name: data["status"] for name, data in events[-1].attributes.items()}
    assert statuses == {"current_level": "SUCCESS", "on_level": "FAILURE"}


async def _configure_level_with_manufacturer_attribute(
    zha_device: ZigbeeDevice, first_response: list
) -> tuple[ZCLAttributeDef, ZCLAttributeDef, list]:
    """Configure two attributes with the same ID under two manufacturer codes.

    zigpy's own `configure_reporting_multiple` sends the standard attribute first and
    the manufacturer-specific one second; the second request times out.
    """
    level = zha_device.device.endpoints[1].level
    standard = general.LevelControl.AttributeDefs.current_level
    manufacturer = dataclasses.replace(
        standard, name="manufacturer_level", manufacturer_code=0x1234
    )
    definitions = {standard.name: standard, manufacturer.name: manufacturer}

    del level.configure_reporting_multiple
    level.find_attribute = definitions.__getitem__
    level._configure_reporting = AsyncMock(side_effect=[first_response, TimeoutError()])

    events: list = []
    zha_device.on_event(ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT, events.append)

    await configure_cluster_configs(
        zha_device,
        {
            (1, 8, True): AggregatedClusterConfig(
                cluster=level,
                attributes={
                    standard.name: AggregatedAttrConfig(reporting=DEFAULT),
                    manufacturer.name: AggregatedAttrConfig(reporting=DEFAULT),
                },
            )
        },
    )

    assert len(level._configure_reporting.mock_calls) == 2
    return standard, manufacturer, events


async def test_configure_reporting_partial_failure_same_attribute_id(
    zha_gateway: Gateway,
) -> None:
    """An attribute configured under one manufacturer code is not another's."""
    zha_device = await join_light(zha_gateway)
    standard, manufacturer, events = await _configure_level_with_manufacturer_attribute(
        zha_device,
        [[zcl_f.ConfigureReportingResponseRecord(status=zcl_f.Status.SUCCESS)]],
    )

    stored = records(zha_device)
    assert (
        stored[reporting_key(1, True, 8, standard.id, None)]["last_attempt"]["status"]
        == "SUCCESS"
    )
    manufacturer_record = stored[reporting_key(1, True, 8, standard.id, 0x1234)]
    assert manufacturer_record["last_attempt"]["error"] == "TimeoutError"
    assert "acknowledged" not in manufacturer_record

    statuses = {name: data["status"] for name, data in events[-1].attributes.items()}
    assert statuses == {"current_level": "SUCCESS", "manufacturer_level": "FAILURE"}


async def test_configure_reporting_partial_failure_keeps_unsupported(
    zha_gateway: Gateway,
) -> None:
    """An attribute the device rejected before a later request raised keeps its status."""
    zha_device = await join_light(zha_gateway)
    standard = general.LevelControl.AttributeDefs.current_level
    (
        _standard,
        _manufacturer,
        events,
    ) = await _configure_level_with_manufacturer_attribute(
        zha_device,
        [
            [
                zcl_f.ConfigureReportingResponseRecord(
                    status=zcl_f.Status.UNSUPPORTED_ATTRIBUTE,
                    direction=zcl_f.ReportingDirection.SendReports,
                    attrid=standard.id,
                )
            ]
        ],
    )

    record = records(zha_device)[reporting_key(1, True, 8, standard.id, None)]
    assert record["last_attempt"] == {
        "time": record["last_attempt"]["time"],
        "status": "UNSUPPORTED_ATTRIBUTE",
    }
    assert events[-1].attributes["current_level"]["status"] == "UNSUPPORTED_ATTRIBUTE"


async def test_recording_failure_does_not_stop_configuration(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """A failure while recording is logged and configuration goes on."""
    zha_device = await join_light(zha_gateway)
    on_off = zha_device.device.endpoints[1].on_off
    level = zha_device.device.endpoints[1].level
    on_off.bind.reset_mock()
    level.configure_reporting_multiple.reset_mock()

    with (
        patch.object(
            AppliedConfigRecorder, "record_binding", side_effect=RuntimeError("bind")
        ),
        patch.object(
            AppliedConfigRecorder,
            "record_reporting",
            side_effect=RuntimeError("reporting"),
        ),
        patch.object(
            AppliedConfigRecorder, "mark_stale", side_effect=RuntimeError("stale")
        ),
    ):
        await zha_device.async_configure()

    assert on_off.bind.mock_calls
    assert level.configure_reporting_multiple.mock_calls
    assert "Failed to record binding of cluster" in caplog.text
    assert "Failed to record reporting configuration of" in caplog.text
    assert "Failed to mark stale configuration records" in caplog.text

    # A value the store cannot hold (NaN) is not recorded but does not fail either
    attrs = general.LevelControl.AttributeDefs
    await configure_cluster_configs(
        zha_device,
        {
            (1, 8, True): AggregatedClusterConfig(
                cluster=level,
                attributes={
                    attrs.current_level.name: AggregatedAttrConfig(
                        reporting=ReportingConfig(
                            min_interval=0,
                            max_interval=900,
                            reportable_change=float("nan"),
                        )
                    )
                },
            )
        },
    )

    # The user bind API returns its results whatever happens to the record
    remote = await join_remote(zha_gateway)
    remote.device.zdo.request = AsyncMock(return_value=[zdo_t.Status.SUCCESS])

    with patch.object(
        AppliedConfigRecorder, "record_binding", side_effect=RuntimeError("user")
    ):
        results = await remote.async_bind_to_device(zha_device)

    assert [r.success for r in results] == [True, True]


async def test_entity_creation_failure_does_not_mark_stale(
    zha_gateway: Gateway,
) -> None:
    """A run after an entity's constructor raised in discovery marks nothing stale.

    Endpoint discovery catches the error itself and reports it to the device. (The
    light's items are also wanted by its configuration entities, so the records alone
    would not show it.)
    """
    zha_device = await join_light(zha_gateway)

    with (
        patch.object(light.Light, "__init__", side_effect=RuntimeError("failed")),
        patch(
            "zha.zigbee.device.configure_cluster_configs",
            wraps=configure_cluster_configs,
        ) as configure,
    ):
        await zha_device.async_configure()

    assert not any(
        isinstance(entity, light.Light) for entity in zha_device._discovered_entities
    )
    assert configure.mock_calls[0].kwargs == {"mark_stale": False}

    # The next complete run marks again
    with patch(
        "zha.zigbee.device.configure_cluster_configs",
        wraps=configure_cluster_configs,
    ) as configure:
        await zha_device.async_configure()

    assert configure.mock_calls[0].kwargs == {"mark_stale": True}


async def test_discovery_failure_does_not_mark_stale(zha_gateway: Gateway) -> None:
    """Items of an entity that failed to be created are not marked stale."""
    zha_device = await join_light(zha_gateway)
    original = zha_device.discover_entities

    def failing_discovery():
        for entity in original():
            if entity.PLATFORM == Platform.LIGHT:
                raise RuntimeError("entity failed")
            yield entity

    with patch.object(zha_device, "discover_entities", side_effect=failing_discovery):
        await zha_device.async_configure()

    stored = records(zha_device)
    assert (
        "stale_since"
        not in stored[binding_key(1, 6, coordinator_destination())]["desired_by"]["zha"]
    )


async def test_one_record_failure_does_not_mark_others_stale(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed record write leaves the other attributes recorded and none stale."""
    zha_device = await join_light(zha_gateway)
    level = zha_device.device.endpoints[1].level
    attrs = general.LevelControl.AttributeDefs
    current_level = reporting_key(1, True, 8, attrs.current_level.id, None)
    on_level = reporting_key(1, True, 8, attrs.on_level.id, None)
    before = records(zha_device)[current_level]
    original = AppliedConfigRecorder._save
    calls = []

    def save(self, key, record):
        calls.append(key)

        # Only the configuration run's write fails, not a later stale mark
        if key == current_level and calls.count(key) == 1:
            raise ValueError("the store refuses the record")

        original(self, key, record)

    with patch.object(AppliedConfigRecorder, "_save", save):
        await configure_cluster_configs(
            zha_device,
            {
                (1, 8, True): AggregatedClusterConfig(
                    cluster=level,
                    attributes={
                        attrs.current_level.name: AggregatedAttrConfig(
                            reporting=DEFAULT
                        ),
                        attrs.on_level.name: AggregatedAttrConfig(reporting=DEFAULT),
                    },
                )
            },
        )

    assert calls[:2] == [current_level, on_level]
    assert "Failed to record reporting configuration of current_level" in caplog.text
    stored = records(zha_device)
    assert on_level in stored
    # The failed record is unchanged and, being wanted, not marked stale
    assert stored[current_level] == before


async def test_reporting_without_manufacturer_code_not_recorded(
    zha_gateway: Gateway,
) -> None:
    """An attribute without a manufacturer code is not recorded.

    Nothing is marked stale either, since its earlier record cannot be told from one
    that is no longer wanted.
    """
    zha_device = await join_light(zha_gateway)
    level = zha_device.device.endpoints[1].level
    attrs = general.LevelControl.AttributeDefs
    before = records(zha_device)

    with patch.object(
        level, "_get_effective_manufacturer_code", side_effect=RuntimeError("no code")
    ):
        await configure_cluster_configs(
            zha_device,
            {
                (1, 8, True): AggregatedClusterConfig(
                    cluster=level,
                    attributes={
                        attrs.current_level.name: AggregatedAttrConfig(
                            reporting=DEFAULT
                        ),
                        attrs.on_level.name: AggregatedAttrConfig(reporting=DEFAULT),
                    },
                )
            },
        )

    assert level.configure_reporting_multiple.mock_calls
    # Neither attribute is recorded, and the On/Off records of the earlier run, which
    # this run did not touch, are not marked stale either
    assert records(zha_device) == before


async def test_unresolved_binding_destination_marks_nothing_stale(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """A binding whose destination cannot be resolved stops stale marking."""
    zha_device = await join_light(zha_gateway)
    app = zha_gateway.application_controller
    before = records(zha_device)

    with patch.object(
        type(app), "get_dst_address", side_effect=RuntimeError("no address")
    ):
        level = zha_device.device.endpoints[1].level
        await configure_cluster_configs(
            zha_device,
            {(1, 8, True): AggregatedClusterConfig(cluster=level, bind=True)},
        )

    assert "Failed to resolve the binding destination" in caplog.text
    assert records(zha_device) == before

    # A destination that cannot be keyed has the same effect
    recorder = AppliedConfigRecorder(zha_device.device)

    with pytest.raises(ValueError):
        recorder.record_binding(
            endpoint_id=1,
            cluster_id=6,
            destination=zdo_t.MultiAddress(addrmode=2),
            operation="bind",
            origin="zha",
            result=ConfigResult(status="SUCCESS"),
        )

    recorder.mark_stale()
    assert records(zha_device) == before


async def test_join_invalidates_acknowledgements(zha_gateway: Gateway) -> None:
    """A device joining again may have been reset: earlier acks are marked."""
    zha_device = await join_light(zha_gateway)
    on_off_key = binding_key(1, 6, coordinator_destination())
    level_key = binding_key(1, 8, coordinator_destination())
    acknowledged = records(zha_device)[on_off_key]["acknowledged"]

    # On a restart nothing joins and nothing is marked
    assert "invalidated" not in acknowledged

    zha_device.device.endpoints[1].on_off.bind = AsyncMock(side_effect=TimeoutError())
    await zha_gateway.async_device_initialized(zha_device.device)
    await zha_gateway.async_block_till_done()

    stored = records(zha_device)
    # Not acknowledged again: the old acknowledgement is kept, marked
    assert stored[on_off_key]["acknowledged"] == {
        **acknowledged,
        "invalidated": {
            "reason": "joined",
            "time": stored[on_off_key]["acknowledged"]["invalidated"]["time"],
        },
    }
    # Acknowledged again: replaced by the new acknowledgement
    assert "invalidated" not in stored[level_key]["acknowledged"]


async def test_coordinator_endpoint_differs(zha_gateway: Gateway) -> None:
    """Bindings to two coordinator endpoints are separate records.

    The radio library can resolve ZHA's bindings to another coordinator endpoint than
    the user bind API uses, as zigpy-znp can.
    """
    app = zha_gateway.application_controller
    get_dst_address = type(app).get_dst_address

    def dst_address(self, cluster):
        destination = get_dst_address(self, cluster)
        destination.endpoint = 2
        return destination

    with patch.object(type(app), "get_dst_address", dst_address):
        light = await join_light(zha_gateway)

    coordinator = zha_gateway.coordinator_zha_device
    assert coordinator is not None
    light.device.endpoints[1].add_output_cluster(general.OnOff.cluster_id)
    light.device.zdo.request = AsyncMock(return_value=[zdo_t.Status.SUCCESS])
    await light.async_bind_to_device(coordinator)

    stored = records(light)
    zha_record = stored[binding_key(1, 6, coordinator_destination(endpoint=2))]
    user_record = stored[binding_key(1, 6, coordinator_destination(endpoint=1))]
    assert zha_record["desired_by"] == {"zha": {"sides": ["server"]}}
    assert zha_record["destination"]["endpoint"] == 2
    assert list(user_record["desired_by"]) == ["user"]
    assert user_record["destination"] == {
        "ieee": COORDINATOR_IEEE,
        "endpoint": 1,
        "coordinator": True,
    }


async def test_reconfigure_updates_and_marks_stale(zha_gateway: Gateway) -> None:
    """A run updates the desired settings and marks what it no longer wants stale."""
    zha_device = await join_light(zha_gateway)
    level = zha_device.device.endpoints[1].level
    attrs = general.LevelControl.AttributeDefs
    relaxed = ReportingConfig(min_interval=5, max_interval=3600, reportable_change=10)
    binding = binding_key(1, 8, coordinator_destination())
    current_level = reporting_key(1, True, 8, attrs.current_level.id, None)
    on_level = reporting_key(1, True, 8, attrs.on_level.id, None)

    def configs(*, bind: bool, with_on_level: bool) -> dict:
        attributes = {attrs.current_level.name: AggregatedAttrConfig(reporting=relaxed)}
        if with_on_level:
            attributes[attrs.on_level.name] = AggregatedAttrConfig(reporting=DEFAULT)
        return {
            (1, 8, True): AggregatedClusterConfig(
                cluster=level, bind=bind, attributes=attributes
            )
        }

    await configure_cluster_configs(zha_device, configs(bind=True, with_on_level=True))
    stored = records(zha_device)
    assert stored[current_level]["desired_by"]["zha"] == {
        "min": 5,
        "max": 3600,
        "change": 10,
    }
    assert stored[current_level]["acknowledged"]["max"] == 3600
    assert on_level in stored

    # The On/Off cluster was not part of this run, so its records are stale now
    on_off_binding = binding_key(1, 6, coordinator_destination())
    assert "stale_since" in stored[on_off_binding]["desired_by"]["zha"]
    assert "stale_since" not in stored[binding]["desired_by"]["zha"]

    await configure_cluster_configs(
        zha_device, configs(bind=False, with_on_level=False)
    )
    stored = records(zha_device)
    stale_since = stored[on_level]["desired_by"]["zha"]["stale_since"]
    # A stale record keeps its history
    assert stored[on_level]["desired_by"]["zha"]["max"] == 900
    assert stored[on_level]["acknowledged"]["max"] == 900
    assert "stale_since" in stored[binding]["desired_by"]["zha"]
    assert "stale_since" not in stored[current_level]["desired_by"]["zha"]

    # Staying unwanted keeps the time it became stale
    await configure_cluster_configs(
        zha_device, configs(bind=False, with_on_level=False)
    )
    assert records(zha_device)[on_level]["desired_by"]["zha"]["stale_since"] == (
        stale_since
    )

    # Wanted again, it is no longer stale
    await zha_device.async_configure()
    stored = records(zha_device)
    assert "stale_since" not in stored[binding]["desired_by"]["zha"]
    assert "stale_since" not in stored[on_off_binding]["desired_by"]["zha"]
    assert "stale_since" in stored[on_level]["desired_by"]["zha"]


async def test_skipped_configuration_keeps_records(zha_gateway: Gateway) -> None:
    """A device that skips configuration does not mark its records stale."""
    zha_device = await join_light(zha_gateway)
    before = records(zha_device)

    with patch.object(
        type(zha_device), "skip_configuration", new_callable=PropertyMock
    ) as skip:
        skip.return_value = True
        await zha_device.async_configure()

    assert records(zha_device) == before


async def test_no_entities_configured_marks_all_stale(zha_gateway: Gateway) -> None:
    """A run with nothing to configure marks ZHA's earlier records stale."""
    zha_device = await join_light(zha_gateway)

    with patch(
        "zha.zigbee.device.aggregate_cluster_configs", return_value={}
    ) as aggregate:
        await zha_device.async_configure()

    assert aggregate.mock_calls
    assert all(
        "stale_since" in record["desired_by"]["zha"]
        for record in records(zha_device).values()
    )


async def test_quirk_handler_marked(zha_gateway: Gateway) -> None:
    """Records note when a quirk cluster replaces the request.

    zhaquirks' `LocalDataCluster` answers binds and reporting configuration itself.
    """
    zha_device = await join_light(zha_gateway)
    on_off = zha_device.device.endpoints[1].on_off

    class LocalOnOff(LocalDataCluster, general.OnOff):
        """An On/Off cluster kept by the quirk."""

    # Let the cluster's own methods run instead of the test doubles
    bind, configure = on_off.bind, on_off.configure_reporting_multiple
    del on_off.bind, on_off.configure_reporting_multiple
    on_off.__class__ = LocalOnOff
    await zha_device.async_configure()

    stored = records(zha_device)
    on_off_binding = stored[binding_key(1, 6, coordinator_destination())]
    on_off_reporting = stored[reporting_key(1, True, 6, 0x0000, None)]
    assert on_off_binding["quirk_handler"] is True
    assert on_off_binding["last_attempt"]["status"] == "SUCCESS"
    assert on_off_reporting["quirk_handler"] is True
    assert on_off_reporting["last_attempt"]["status"] == "SUCCESS"
    assert "quirk_handler" not in stored[binding_key(1, 8, coordinator_destination())]

    on_off.__class__ = general.OnOff
    on_off.bind, on_off.configure_reporting_multiple = bind, configure
    await zha_device.async_configure()
    assert (
        "quirk_handler"
        not in records(zha_device)[binding_key(1, 6, coordinator_destination())]
    )


async def test_newer_record_left_alone(zha_gateway: Gateway) -> None:
    """A record written by a newer version is not overwritten."""
    zha_device = await join_light(zha_gateway)
    namespace = zha_device.device.store.namespace(APPLIED_CONFIG_NAMESPACE)
    key = binding_key(1, 6, coordinator_destination())
    namespace.set(key, {"future": True}, version=2)

    await zha_device.async_configure()
    assert namespace[key] == {"future": True}
    assert namespace.item(key).version == 2


async def test_nothing_recorded_without_store(zha_gateway: Gateway) -> None:
    """Devices without a real store, as on a mocked application, record nothing."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_LIGHT,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee=LIGHT_IEEE,
    )
    mock_store = MagicMock()

    with patch.object(
        type(zigpy_device), "store", new_callable=PropertyMock, return_value=mock_store
    ):
        zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
        await zha_device.async_configure()
        results = await zha_device.async_bind_to_group(0x1001, [])

        assert not AppliedConfigRecorder(zigpy_device).enabled

    assert results == []
    assert zigpy_device.endpoints[1].on_off.bind.mock_calls
    assert mock_store.mock_calls == []
    assert len(zigpy_device.store.namespace(APPLIED_CONFIG_NAMESPACE)) == 0

    # The recorder ignores writes when disabled
    recorder = AppliedConfigRecorder(MagicMock())
    recorder.record_binding(
        endpoint_id=1,
        cluster_id=6,
        destination=coordinator_destination(),
        operation="bind",
        origin="user",
        result=ConfigResult(status="SUCCESS"),
    )
    recorder.mark_stale()


async def test_bind_to_device(zha_gateway: Gateway) -> None:
    """Binding a device to another returns and records the outcome per cluster."""
    light = await join_light(zha_gateway)
    remote = await join_remote(zha_gateway)
    destination = zdo_t.MultiAddress(addrmode=3, ieee=light.ieee, endpoint=1)
    on_off_key = binding_key(1, 6, destination)
    level_key = binding_key(1, 8, destination)

    remote.device.zdo.request = AsyncMock(
        side_effect=[[zdo_t.Status.SUCCESS], [zdo_t.Status.TABLE_FULL]]
    )
    results = await remote.async_bind_to_device(light)

    assert [(r.cluster_id, r.status, r.error, r.success) for r in results] == [
        (6, "SUCCESS", None, True),
        (8, "TABLE_FULL", None, False),
    ]
    assert results[0].as_dict() == {
        "endpoint_id": 1,
        "cluster_id": 6,
        "destination": {"ieee": LIGHT_IEEE, "endpoint": 1},
        "status": "SUCCESS",
        "error": None,
        "success": True,
    }
    json.dumps([result.as_dict() for result in results])
    assert [call.args for call in remote.device.zdo.request.mock_calls] == [
        (zdo_t.ZDOCmd.Bind_req, remote.ieee, 1, 6, destination),
        (zdo_t.ZDOCmd.Bind_req, remote.ieee, 1, 8, destination),
    ]

    stored = records(remote)
    assert stored[on_off_key] == {
        "kind": "binding",
        "endpoint": 1,
        "cluster_id": 6,
        "destination": {"ieee": LIGHT_IEEE, "endpoint": 1},
        "desired_by": {
            "user": {"bound": True, "time": stored[on_off_key]["last_attempt"]["time"]}
        },
        "last_attempt": {
            "time": stored[on_off_key]["last_attempt"]["time"],
            "operation": "bind",
            "origin": "user",
            "status": "SUCCESS",
        },
        "acknowledged": {
            "bound": True,
            "time": stored[on_off_key]["last_attempt"]["time"],
        },
    }
    assert stored[level_key]["desired_by"]["user"]["bound"] is True
    assert stored[level_key]["last_attempt"]["status"] == "TABLE_FULL"
    assert "acknowledged" not in stored[level_key]

    # A user's bindings are not ZHA's to mark stale
    await remote.async_configure()
    assert "stale_since" not in json.dumps(records(remote)[on_off_key])

    # Unbinding keeps the intent as a tombstone. A binding the device does not have
    # is unbound already.
    remote.device.zdo.request = AsyncMock(
        side_effect=[
            [zdo_t.Status.NO_ENTRY],
            zigpy.exceptions.DeliveryError("failed"),
        ]
    )
    results = await remote.async_unbind_from_device(light)

    assert [(r.cluster_id, r.status, r.error, r.success) for r in results] == [
        (6, "NO_ENTRY", None, True),
        (8, None, "DeliveryError", False),
    ]
    assert remote.device.zdo.request.mock_calls[0].args[0] == zdo_t.ZDOCmd.Unbind_req

    stored = records(remote)
    assert stored[on_off_key]["desired_by"]["user"]["bound"] is False
    assert stored[on_off_key]["acknowledged"]["bound"] is False
    assert stored[level_key]["desired_by"]["user"]["bound"] is False
    assert stored[level_key]["last_attempt"]["error"] == "DeliveryError"
    assert "acknowledged" not in stored[level_key]


async def test_bind_to_coordinator_shares_zha_record(zha_gateway: Gateway) -> None:
    """A user's binding to the coordinator is the same record as ZHA's own."""
    light = await join_light(zha_gateway)
    coordinator = zha_gateway.coordinator_zha_device
    assert coordinator is not None

    # The light has no bindable output clusters; give it an On/Off client
    light.device.endpoints[1].add_output_cluster(general.OnOff.cluster_id)
    light.device.zdo.request = AsyncMock(return_value=[zdo_t.Status.SUCCESS])
    results = await light.async_unbind_from_device(coordinator)

    destination = coordinator_destination()
    assert [(r.cluster_id, r.destination, r.success) for r in results] == [
        (6, {"ieee": COORDINATOR_IEEE, "endpoint": 1, "coordinator": True}, True)
    ]

    record = records(light)[binding_key(1, 6, destination)]
    assert record["destination"]["coordinator"] is True
    assert record["desired_by"]["zha"] == {"sides": ["server"]}
    assert record["desired_by"]["user"]["bound"] is False
    assert record["acknowledged"]["bound"] is False


async def test_bind_to_group(zha_gateway: Gateway) -> None:
    """Group bindings return their outcome and are recorded as user-made."""
    remote = await join_remote(zha_gateway)
    destination = zdo_t.MultiAddress(addrmode=1, nwk=0x1001)

    remote.device.zdo.request = AsyncMock(
        side_effect=[[zdo_t.Status.SUCCESS], TimeoutError()]
    )
    results = await remote.async_bind_to_group(
        0x1001,
        [
            # Endpoint 0 and clusters that are not outputs are skipped
            _binding("on_off", 6, 1),
            _binding("level", 8, 1),
            _binding("basic", 0, 1),
            _binding("on_off", 6, 0),
        ],
    )

    assert [(r.cluster_id, r.status, r.error, r.success) for r in results] == [
        (6, "SUCCESS", None, True),
        (8, None, "TimeoutError", False),
    ]
    assert results[0].destination == {"group": 0x1001}

    stored = records(remote)
    record = stored[binding_key(1, 6, destination)]
    assert record["destination"] == {"group": 0x1001}
    assert record["desired_by"]["user"]["bound"] is True
    assert stored[binding_key(1, 8, destination)]["last_attempt"]["error"] == (
        "TimeoutError"
    )

    remote.device.zdo.request = AsyncMock(return_value=[zdo_t.Status.SUCCESS])
    results = await remote.async_unbind_from_group(0x1001, [_binding("on_off", 6, 1)])
    assert [r.success for r in results] == [True]
    assert records(remote)[binding_key(1, 6, destination)]["acknowledged"] == {
        "bound": False,
        "time": records(remote)[binding_key(1, 6, destination)]["last_attempt"]["time"],
    }


def _binding(name: str, cluster_id: int, endpoint_id: int) -> ClusterBinding:
    """Return a cluster binding as Home Assistant sends it."""
    return ClusterBinding(name=name, type="out", id=cluster_id, endpoint_id=endpoint_id)


async def test_diagnostics(zha_gateway: Gateway) -> None:
    """Records are shown in diagnostics, with IEEE addresses in keys replaced."""
    light = await join_light(zha_gateway)

    diagnostics = json.loads(
        json.dumps(light.get_diagnostics_json(), cls=ZhaJsonEncoder)
    )
    store = diagnostics["store"][APPLIED_CONFIG_NAMESPACE]

    assert "binding/0x0001/0x0006/ieee/<ieee 1>/0x0001" in store
    assert "reporting/0x0001/server/0x0006/0x0000/-" in store
    assert COORDINATOR_IEEE not in json.dumps(list(store))
    entry = store["binding/0x0001/0x0006/ieee/<ieee 1>/0x0001"]
    assert entry["version"] == 1
    assert entry["value"]["destination"] == {
        "ieee": COORDINATOR_IEEE,
        "endpoint": 1,
        "coordinator": True,
    }

    # Fixtures in tests/data/devices leave out what a test run configured
    assert "store" not in get_fixture_diagnostics_json(light)


async def test_diagnostics_user_bindings(zha_gateway: Gateway) -> None:
    """Destinations of a user's bindings are replaced in keys too."""
    light = await join_light(zha_gateway)
    remote = await join_remote(zha_gateway)
    remote.device.zdo.request = AsyncMock(return_value=[zdo_t.Status.SUCCESS])
    await remote.async_bind_to_device(light)

    diagnostics = json.loads(
        json.dumps(remote.get_diagnostics_json(), cls=ZhaJsonEncoder)
    )
    store = diagnostics["store"][APPLIED_CONFIG_NAMESPACE]

    # ZHA binds the remote's client clusters to the coordinator, whose address
    # sorts first
    assert sorted(store) == [
        "binding/0x0001/0x0006/ieee/<ieee 1>/0x0001",
        "binding/0x0001/0x0006/ieee/<ieee 2>/0x0001",
        "binding/0x0001/0x0008/ieee/<ieee 1>/0x0001",
        "binding/0x0001/0x0008/ieee/<ieee 2>/0x0001",
    ]
    assert LIGHT_IEEE not in json.dumps(list(store))
    assert COORDINATOR_IEEE not in json.dumps(list(store))
    entry = store["binding/0x0001/0x0006/ieee/<ieee 2>/0x0001"]
    assert entry["value"]["destination"] == {"ieee": LIGHT_IEEE, "endpoint": 1}
    assert entry["value"]["desired_by"]["user"]["bound"] is True
    coordinator_entry = store["binding/0x0001/0x0008/ieee/<ieee 1>/0x0001"]
    assert coordinator_entry["value"]["destination"]["coordinator"] is True
    assert coordinator_entry["value"]["desired_by"]["zha"] == {"sides": ["client"]}
