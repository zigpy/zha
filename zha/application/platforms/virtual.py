"""Virtual platform entities.

Virtual entities participate in cluster discovery and the cluster-config
aggregation flow (so they drive bind, attribute reporting, and cluster-level
setup work) but are filtered out before being registered as HA entities. They
host per-cluster background work like IAS Zone enrollment, LightLink
coordinator group joining, and client-cluster attribute cache synchronization.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from zhaquirks.quirk_ids import TUYA_PLUG_MANUFACTURER
import zigpy.exceptions
import zigpy.types as t
import zigpy.zcl
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.closures import DoorLock, WindowCovering
from zigpy.zcl.clusters.general import Identify, LevelControl, OnOff, Ota, Scenes
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.clusters.lightlink import LightLink
from zigpy.zcl.clusters.security import IasZone
from zigpy.zcl.foundation import GENERAL_COMMANDS, CommandSchema, GeneralCommand

from zha.application import Platform
from zha.application.helpers import write_attributes_safe
from zha.application.platforms import (
    AttrConfig,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.const import (
    AQARA_OPPLE_CLUSTER,
    IKEA_REMOTE_CLUSTER,
    IKEA_SHORTCUT_V1_CLUSTER,
    INOVELLI_CLUSTER,
    OSRAM_CLUSTER,
    PHILIPS_REMOTE_CLUSTER,
    SINOPE_MANUFACTURER_CLUSTER,
    SMARTTHINGS_ACCELERATION_CLUSTER,
    SONOFF_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
)
from zha.exceptions import ZHAException
from zha.zigbee.endpoint import cluster_event_unique_id, split_event_arg

ATTRIBUTE_ID = "attribute_id"
ATTRIBUTE_NAME = "attribute_name"
ATTRIBUTE_VALUE = "attribute_value"
SIGNAL_ATTR_UPDATED = "attribute_updated"
VALUE = "value"

UNKNOWN = "Unknown"

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


class VirtualEntity(PlatformEntity):
    """Cluster-level background driver that isn't registered as a HA entity.

    Virtual entities participate in discovery and cluster-config aggregation
    (so they bind, configure reporting, and run cluster-level setup work like
    IAS Zone enrollment) but the wrapping integration is expected to skip
    registering them with Home Assistant. They have no state surface and
    exist purely to drive cluster-level background work.
    """

    PLATFORM = Platform.VIRTUAL
    _attr_always_supported = True

    def on_add(self) -> None:
        """Subscribe to incoming cluster commands and attribute events."""
        super().on_add()
        if hasattr(self, "cluster_command"):
            self._cluster.add_listener(self)
            self._on_remove_callbacks.append(
                lambda: self._cluster.remove_listener(self)
            )

        if hasattr(self, "handle_attribute_updated"):
            for event_type in (
                AttributeReadEvent,
                AttributeReportedEvent,
                AttributeUpdatedEvent,
                AttributeWrittenEvent,
            ):
                unsub = self._cluster.on_event(
                    event_type.event_type, self.handle_attribute_updated
                )
                self._on_remove_callbacks.append(unsub)

    def emit_cluster_zha_event(
        self, command: str, arg: list | dict | CommandSchema | None = None
    ) -> None:
        """Relay a cluster-level zha_event via the endpoint."""
        args, params = split_event_arg(command, arg)
        self._endpoint.emit_zha_event(
            {
                "unique_id": cluster_event_unique_id(self._endpoint, self._cluster),
                "cluster_id": self._cluster.cluster_id,
                "command": command,
                "args": args,
                "params": params,
            }
        )


@register_entity(IasZone.cluster_id)
class IasZoneEnrollment(VirtualEntity):
    """Drives the IAS Zone enrollment handshake.

    Writes the coordinator's IEEE to `cie_addr`, sends a pro-active enroll
    response, replies to device-initiated enroll requests, and mirrors
    status_change_notification commands into the `zone_status` attribute cache.
    """

    _unique_id_suffix = "ias_zone_enrollment"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasZone.cluster_id}),
    )

    _server_cluster_config = {
        IasZone.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                IasZone.AttributeDefs.zone_type: AttrConfig(read_on_startup=True),
            },
        ),
    }

    async def async_configure_cluster(self, cluster: zigpy.zcl.Cluster) -> None:
        """Write CIE address and send the pro-active enroll response."""
        ieee = cluster.endpoint.device.application.state.node_info.ieee

        try:
            await write_attributes_safe(
                cluster, {IasZone.AttributeDefs.cie_addr.name: ieee}
            )
            self.debug(
                "wrote cie_addr: %s to '%s' cluster", str(ieee), cluster.ep_attribute
            )
        except ZHAException as ex:
            self.debug(
                "Failed to write cie_addr to '%s' cluster: %s",
                cluster.ep_attribute,
                str(ex),
            )

        self.debug("Sending pro-active IAS enroll response")
        cluster.create_catching_task(
            cluster.enroll_response(
                enroll_response_code=IasZone.EnrollResponse.Success, zone_id=0
            )
        )

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Handle incoming IAS Zone client commands."""
        if command_id == IasZone.ClientCommandDefs.status_change_notification.id:
            zone_status = args[0]
            self._cluster.update_attribute(
                IasZone.AttributeDefs.zone_status.id, zone_status
            )
            self.debug("Updated alarm state: %s", zone_status)
        elif command_id == IasZone.ClientCommandDefs.enroll.id:
            self.debug("Enroll requested")
            self._cluster.create_catching_task(
                self._cluster.enroll_response(
                    enroll_response_code=IasZone.EnrollResponse.Success, zone_id=0
                )
            )


@register_entity(LightLink.cluster_id)
class LightLinkGroupJoin(VirtualEntity):
    """Adds the coordinator to the device's LightLink groups."""

    _unique_id_suffix = "lightlink_group_join"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LightLink.cluster_id}),
    )

    _server_cluster_config = {
        LightLink.cluster_id: ClusterConfig(bind=False),
    }

    async def async_configure_cluster(self, cluster: zigpy.zcl.Cluster) -> None:
        """Query the device's groups and add the coordinator to each."""
        application = cluster.endpoint.device.application
        try:
            coordinator = application.get_device(application.state.node_info.ieee)
        except KeyError:
            self.warning("Aborting - unable to locate required coordinator device.")
            return

        try:
            rsp = await cluster.get_group_identifiers(0)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            self.warning("Couldn't get list of groups: %s", str(exc))
            return

        if isinstance(rsp, GENERAL_COMMANDS[GeneralCommand.Default_Response].schema):
            groups = []
        else:
            groups = rsp.group_info_records

        if groups:
            for group in groups:
                self.debug("Adding coordinator to 0x%04x group id", group.group_id)
                await coordinator.add_to_group(group.group_id)
        else:
            await coordinator.add_to_group(0x0000, name="Lightlink Group")


@register_entity(OnOff.cluster_id)
class OnOffClientCacheSync(VirtualEntity):
    """Mirrors incoming OnOff client commands to the server attribute cache.

    Lets `Opening`/`IkeaMotion`/`PhilipsMotion` binary sensors (which read the
    server `on_off` cache) stay in sync with `off`/`on`/`toggle`/
    `on_with_timed_off` commands the device sends.
    """

    _unique_id_suffix = "on_off_client_cache_sync"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({OnOff.cluster_id}),
        match_renamed_clusters=True,
    )

    _client_cluster_config = {
        OnOff.cluster_id: ClusterConfig(bind=True),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the OnOff client cache sync."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._off_listener: asyncio.TimerHandle | None = None

    async def on_remove(self) -> None:
        """Cancel tasks and timers this entity owns."""
        if self._off_listener is not None:
            self._off_listener.cancel()
            self._off_listener = None

        await super().on_remove()

    @property
    def on_off(self) -> bool | None:
        """Return cached value of on/off attribute."""
        return self._cluster.get(OnOff.AttributeDefs.on_off.name)

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Mirror commands from the device into the server cache + emit zha_event."""
        try:
            cmd = self._cluster.server_commands[command_id].name
        except KeyError:
            return

        # Process the command into the cache first, so the resulting
        # attribute_updated zha_event fires before the command zha_event.
        if cmd in (
            OnOff.ServerCommandDefs.off.name,
            OnOff.ServerCommandDefs.off_with_effect.name,
        ):
            self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.false)
        elif cmd in (
            OnOff.ServerCommandDefs.on.name,
            OnOff.ServerCommandDefs.on_with_recall_global_scene.name,
        ):
            self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.true)
        elif cmd == OnOff.ServerCommandDefs.on_with_timed_off.name:
            should_accept = args[0]
            on_time = args[1]
            if should_accept == 0 or (should_accept == 1 and bool(self.on_off)):
                if self._off_listener is not None:
                    self._off_listener.cancel()
                    self._off_listener = None
                self._cluster.update_attribute(
                    OnOff.AttributeDefs.on_off.id, t.Bool.true
                )
                if on_time > 0:
                    self._off_listener = asyncio.get_running_loop().call_later(
                        on_time / 10, self._set_to_off
                    )
        elif cmd == "toggle":
            self._cluster.update_attribute(
                OnOff.AttributeDefs.on_off.id, not bool(self.on_off)
            )

        # Re-emit every incoming server command as a zha_event so HA
        # automations can react to remote button presses.
        self.emit_cluster_zha_event(cmd, args)

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Relay attribute updates on this client cluster as zha_events."""
        self.emit_cluster_zha_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTRIBUTE_ID: event.attribute_id,
                ATTRIBUTE_NAME: event.attribute_name or UNKNOWN,
                ATTRIBUTE_VALUE: event.value,
                VALUE: event.value,
            },
        )

    def _set_to_off(self) -> None:
        """Clear the on_off cache when the timed_off duration elapses."""
        self._off_listener = None
        self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.false)


class _ClientClusterZhaEventEmitter(VirtualEntity):
    """Bind a client cluster and emit zha_events for incoming commands/updates."""

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Relay incoming client cluster commands as zha_events."""
        if (
            self._cluster.server_commands is not None
            and self._cluster.server_commands.get(command_id) is not None
        ):
            self.emit_cluster_zha_event(
                self._cluster.server_commands[command_id].name, args
            )

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Relay client cluster attribute updates as zha_events."""
        self.emit_cluster_zha_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTRIBUTE_ID: event.attribute_id,
                ATTRIBUTE_NAME: event.attribute_name or UNKNOWN,
                ATTRIBUTE_VALUE: event.value,
                VALUE: event.value,
            },
        )


@register_entity(Scenes.cluster_id)
class ScenesClientBind(_ClientClusterZhaEventEmitter):
    """Bind the Scenes client cluster and emit zha_events for its commands."""

    _unique_id_suffix = "scenes_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({Scenes.cluster_id}),
        match_renamed_clusters=True,
    )
    _client_cluster_config = {
        Scenes.cluster_id: ClusterConfig(bind=True),
    }


@register_entity(LevelControl.cluster_id)
class LevelControlClientBind(_ClientClusterZhaEventEmitter):
    """Bind LevelControl client cluster and emit zha_events for its commands."""

    _unique_id_suffix = "level_control_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({LevelControl.cluster_id}),
        match_renamed_clusters=True,
        profile_ids=None,
    )
    _client_cluster_config = {
        LevelControl.cluster_id: ClusterConfig(bind=True),
    }


@register_entity(Color.cluster_id)
class ColorClientBind(_ClientClusterZhaEventEmitter):
    """Bind the Color client cluster and emit zha_events for its commands."""

    _unique_id_suffix = "color_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({Color.cluster_id}),
        match_renamed_clusters=True,
    )
    _client_cluster_config = {
        Color.cluster_id: ClusterConfig(bind=True),
    }


@register_entity(WindowCovering.cluster_id)
class WindowCoveringClientBind(_ClientClusterZhaEventEmitter):
    """Bind WindowCovering client cluster and emit zha_events for its commands."""

    _unique_id_suffix = "window_covering_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({WindowCovering.cluster_id}),
        match_renamed_clusters=True,
    )
    _client_cluster_config = {
        WindowCovering.cluster_id: ClusterConfig(bind=True),
    }


@register_entity(PHILIPS_REMOTE_CLUSTER)
class PhilipsRemoteBind(VirtualEntity):
    """Bind the Philips remote cluster on every device that exposes it."""

    _unique_id_suffix = "philips_remote_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({PHILIPS_REMOTE_CLUSTER}),
    )
    _server_cluster_config = {
        PHILIPS_REMOTE_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(OSRAM_CLUSTER)
class OsramClusterBind(VirtualEntity):
    """Bind the Osram manufacturer cluster on every device that exposes it."""

    _unique_id_suffix = "osram_cluster_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OSRAM_CLUSTER}),
    )
    _server_cluster_config = {
        OSRAM_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(Ota.cluster_id)
class OtaCurrentFileVersionCache(VirtualEntity):
    """Updates `current_file_version` on every query_next_image from the device."""

    _unique_id_suffix = "ota_current_file_version_cache"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({Ota.cluster_id}),
    )

    _client_cluster_config = {
        Ota.cluster_id: ClusterConfig(bind=False),
    }

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Capture current_file_version from query_next_image."""
        if command_id not in self._cluster.server_commands:
            return
        cmd_name = self._cluster.server_commands[command_id].name
        if cmd_name == Ota.ServerCommandDefs.query_next_image.name:
            self._cluster.update_attribute(
                Ota.AttributeDefs.current_file_version.id, args[3]
            )


@register_entity(DoorLock.cluster_id)
class DoorLockOperationEvent(VirtualEntity):
    """Emits zha_event for DoorLock operation_event_notification commands."""

    _unique_id_suffix = "door_lock_operation_event"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({DoorLock.cluster_id}),
    )

    _server_cluster_config = {
        DoorLock.cluster_id: ClusterConfig(bind=False),
    }

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Translate operation_event_notification into a zha_event."""
        if (
            self._cluster.client_commands is None
            or self._cluster.client_commands.get(command_id) is None
        ):
            return

        command_name = self._cluster.client_commands[command_id].name
        if command_name != DoorLock.ClientCommandDefs.operation_event_notification.name:
            return

        self.emit_cluster_zha_event(
            command_name,
            {
                "source": args[0].name,
                "operation": args[1].name,
                "code_slot": (args[2] + 1),
            },
        )


@register_entity(SMARTTHINGS_ACCELERATION_CLUSTER)
class SmartThingsAccelerationEvent(VirtualEntity):
    """Emits a zha_event for every attribute update on the SmartThings accel cluster."""

    _unique_id_suffix = "smartthings_acceleration_event"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SMARTTHINGS_ACCELERATION_CLUSTER}),
        manufacturers=frozenset({"CentraLite", "Samjin", "SmartThings"}),
    )

    _server_cluster_config = {
        SMARTTHINGS_ACCELERATION_CLUSTER: ClusterConfig(bind=False),
    }

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Re-emit the update as a zha_event."""
        self.emit_cluster_zha_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTRIBUTE_ID: event.attribute_id,
                ATTRIBUTE_NAME: event.attribute_name or UNKNOWN,
                ATTRIBUTE_VALUE: event.value,
            },
        )


@register_entity(Identify.cluster_id)
class IdentifyTriggerEffectEvent(VirtualEntity):
    """Emits a zha_event when the device sends `trigger_effect`."""

    _unique_id_suffix = "identify_trigger_effect_event"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Identify.cluster_id}),
    )

    _server_cluster_config = {
        Identify.cluster_id: ClusterConfig(bind=False),
    }

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Translate trigger_effect into a zha_event."""
        try:
            cmd = self._cluster.server_commands[command_id].name
        except KeyError:
            return
        if cmd == Identify.ServerCommandDefs.trigger_effect.name:
            self.emit_cluster_zha_event(
                f"{cluster_event_unique_id(self._endpoint, self._cluster)}_{cmd}",
                [args[0]],
            )


# === Aqara Opple cluster per-model attribute initialization ===
#
# Each virtual entity below targets a specific Aqara model and declares the
# Opple attributes that should be populated in the attribute cache on startup
# so the regular entities (select/switch/sensor/number) reading them have a
# value to display.


class _AqaraOppleInitBase(VirtualEntity):
    """Base for per-model Aqara Opple cluster attribute initialization."""

    _unique_id_suffix = "aqara_opple_init"


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraOppleBind(VirtualEntity):
    """Bind the Aqara Opple cluster on every device that exposes it."""

    _unique_id_suffix = "aqara_opple_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionAc02Init(_AqaraOppleInitBase):
    """Aqara P1 motion sensor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac02"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "detection_interval": AttrConfig(read_on_startup=False),
                "motion_sensitivity": AttrConfig(read_on_startup=False),
                "trigger_indicator": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionAgl04Init(_AqaraOppleInitBase):
    """Aqara high-precision motion sensor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.agl04"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "detection_interval": AttrConfig(read_on_startup=False),
                "motion_sensitivity": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionAc01Init(_AqaraOppleInitBase):
    """Aqara FP1 presence sensor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac01"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "presence": AttrConfig(read_on_startup=False),
                "monitoring_mode": AttrConfig(read_on_startup=False),
                "motion_sensitivity": AttrConfig(read_on_startup=False),
                "approach_distance": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPlugInit(_AqaraOppleInitBase):
    """Aqara EU plug attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.plug.mmeu01", "lumi.plug.maeu01"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "power_outage_memory": AttrConfig(read_on_startup=False),
                "consumer_connected": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraFeederInit(_AqaraOppleInitBase):
    """Aqara pet feeder attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "portions_dispensed": AttrConfig(read_on_startup=False),
                "weight_dispensed": AttrConfig(read_on_startup=False),
                "error_detected": AttrConfig(read_on_startup=False),
                "disable_led_indicator": AttrConfig(read_on_startup=False),
                "child_lock": AttrConfig(read_on_startup=False),
                "feeding_mode": AttrConfig(read_on_startup=False),
                "serving_size": AttrConfig(read_on_startup=False),
                "portion_weight": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatAgl001Init(_AqaraOppleInitBase):
    """Aqara E1 radiator thermostat attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "system_mode": AttrConfig(read_on_startup=False),
                "preset": AttrConfig(read_on_startup=False),
                "window_detection": AttrConfig(read_on_startup=False),
                "valve_detection": AttrConfig(read_on_startup=False),
                "valve_alarm": AttrConfig(read_on_startup=False),
                "child_lock": AttrConfig(read_on_startup=False),
                "away_preset_temperature": AttrConfig(read_on_startup=False),
                "window_open": AttrConfig(read_on_startup=False),
                "calibrated": AttrConfig(read_on_startup=False),
                "schedule": AttrConfig(read_on_startup=False),
                "sensor": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraSmokeAcn03Init(_AqaraOppleInitBase):
    """Aqara smoke sensor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.sensor_smoke.acn03"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "buzzer_manual_mute": AttrConfig(read_on_startup=False),
                "smoke_density": AttrConfig(read_on_startup=False),
                "heartbeat_indicator": AttrConfig(read_on_startup=False),
                "buzzer_manual_alarm": AttrConfig(read_on_startup=False),
                "buzzer": AttrConfig(read_on_startup=False),
                "linkage_alarm": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMagnetAc01Init(_AqaraOppleInitBase):
    """Aqara P1 door sensor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.magnet.ac01"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "detection_distance": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraSwitchAcn047Init(_AqaraOppleInitBase):
    """Aqara H1M wall switch attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.switch.acn047"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "switch_mode": AttrConfig(read_on_startup=False),
                "switch_type": AttrConfig(read_on_startup=False),
                "startup_on_off": AttrConfig(read_on_startup=False),
                "decoupled_mode": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraCurtainAgl001Init(_AqaraOppleInitBase):
    """Aqara E1 curtain motor attribute init."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.curtain.agl001"}),
    )
    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "hooks_state": AttrConfig(read_on_startup=False),
                "hooks_lock": AttrConfig(read_on_startup=False),
                "positions_stored": AttrConfig(read_on_startup=False),
                "light_level": AttrConfig(read_on_startup=False),
                "hand_open": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionDetectionIntervalSync(_AqaraOppleInitBase):
    """Propagate the Aqara motion sensor's `detection_interval` to `ias_zone.reset_s`.

    Runs after attribute init so `detection_interval` is in the cache.
    """

    _unique_id_suffix = "aqara_motion_detection_interval_sync"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac02", "lumi.motion.agl04"}),
    )

    _server_cluster_config = {
        AQARA_OPPLE_CLUSTER: ClusterConfig(
            attributes={
                "detection_interval": AttrConfig(read_on_startup=False),
            },
        ),
    }

    async def async_initialize_cluster(self, cluster: zigpy.zcl.Cluster) -> None:
        """Mirror detection_interval into the sibling IAS Zone handler."""
        interval = cluster.get("detection_interval", cluster.get(0x0102))
        if interval is None:
            return
        ias_zone = getattr(cluster.endpoint, "ias_zone", None)
        if ias_zone is None:
            return
        self.debug("Loaded detection interval at startup: %s", interval)
        ias_zone.reset_s = int(interval)


# === Other manufacturer-specific clusters ===


@register_entity(SONOFF_CLUSTER)
class SonoffManufacturerBind(VirtualEntity):
    """Bind the Sonoff manufacturer cluster on every device that exposes it."""

    _unique_id_suffix = "sonoff_manufacturer_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SONOFF_CLUSTER}),
    )
    _server_cluster_config = {
        SONOFF_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(SONOFF_CLUSTER)
class SonoffPresenceSensorInit(VirtualEntity):
    """Sonoff SNZB-06P presence sensor attribute init."""

    _unique_id_suffix = "sonoff_presence_sensor_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SONOFF_CLUSTER}),
        models=frozenset({"SNZB-06P"}),
    )
    _server_cluster_config = {
        SONOFF_CLUSTER: ClusterConfig(
            attributes={
                "last_illumination_state": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class TuyaManufacturerBind(VirtualEntity):
    """Bind the Tuya manufacturer cluster on every device that exposes it."""

    _unique_id_suffix = "tuya_manufacturer_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
    )
    _server_cluster_config = {
        TUYA_MANUFACTURER_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class TuyaPlugManufacturerInit(VirtualEntity):
    """Tuya plug manufacturer-cluster attribute init."""

    _unique_id_suffix = "tuya_plug_manufacturer_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        exposed_features=frozenset({TUYA_PLUG_MANUFACTURER}),
    )
    _server_cluster_config = {
        TUYA_MANUFACTURER_CLUSTER: ClusterConfig(
            attributes={
                "backlight_mode": AttrConfig(read_on_startup=False),
                "power_on_state": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeManufacturerBind(VirtualEntity):
    """Bind the Sinope manufacturer cluster on every device that exposes it."""

    _unique_id_suffix = "sinope_manufacturer_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
    )
    _server_cluster_config = {
        SINOPE_MANUFACTURER_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeSwitchInit(VirtualEntity):
    """Sinope SW2500/DM2500/DM2550 manufacturer-cluster init + reporting."""

    _unique_id_suffix = "sinope_switch_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=frozenset(
            {
                "SW2500ZB",
                "SW2500ZB-G2",
                "DM2500ZB",
                "DM2500ZB-G2",
                "DM2550ZB",
                "DM2550ZB-G2",
            }
        ),
    )
    _server_cluster_config = {
        SINOPE_MANUFACTURER_CLUSTER: ClusterConfig(
            bind=True,
            attributes={
                "double_up_full": AttrConfig(read_on_startup=False),
                "on_led_color": AttrConfig(read_on_startup=False),
                "off_led_color": AttrConfig(read_on_startup=False),
                "off_led_intensity": AttrConfig(read_on_startup=False),
                "on_led_intensity": AttrConfig(read_on_startup=False),
                "action_report": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=0, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeDimmerInit(VirtualEntity):
    """Extra Sinope dimmer attribute (DM2500/DM2550 only)."""

    _unique_id_suffix = "sinope_dimmer_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=frozenset({"DM2500ZB", "DM2500ZB-G2", "DM2550ZB", "DM2550ZB-G2"}),
    )
    _server_cluster_config = {
        SINOPE_MANUFACTURER_CLUSTER: ClusterConfig(
            attributes={
                "on_intensity": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(IKEA_REMOTE_CLUSTER)
class IkeaRemoteClientBind(VirtualEntity):
    """Bind the IKEA remote client cluster on every device that exposes it.

    The accompanying quirk (`EventableCluster`) emits its own zha_events for
    received commands, so the only thing we still need is the bind.
    """

    _unique_id_suffix = "ikea_remote_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({IKEA_REMOTE_CLUSTER}),
        match_renamed_clusters=True,
    )
    _client_cluster_config = {
        IKEA_REMOTE_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(IKEA_REMOTE_CLUSTER)
class IkeaRemoteServerBind(VirtualEntity):
    """Bind the IKEA remote server cluster on every device that exposes it."""

    _unique_id_suffix = "ikea_remote_server_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IKEA_REMOTE_CLUSTER}),
        match_renamed_clusters=True,
    )
    _server_cluster_config = {
        IKEA_REMOTE_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(IKEA_SHORTCUT_V1_CLUSTER)
class IkeaSymfoniskRemoteClientBind(VirtualEntity):
    """Bind the IKEA Symfonisk shortcut v1 client cluster."""

    _unique_id_suffix = "ikea_shortcut_v1_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({IKEA_SHORTCUT_V1_CLUSTER}),
        match_renamed_clusters=True,
    )
    _client_cluster_config = {
        IKEA_SHORTCUT_V1_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliBind(VirtualEntity):
    """Bind the Inovelli manufacturer cluster on every device that exposes it."""

    _unique_id_suffix = "inovelli_bind"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )
    _server_cluster_config = {
        INOVELLI_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliClientBind(VirtualEntity):
    """Bind the Inovelli manufacturer client cluster on every device that exposes it."""

    _unique_id_suffix = "inovelli_client_bind"

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({INOVELLI_CLUSTER}),
    )
    _client_cluster_config = {
        INOVELLI_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliVzm30Init(VirtualEntity):
    """Inovelli VZM30-SN switch attribute init."""

    _unique_id_suffix = "inovelli_vzm30_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM30-SN"}),
    )
    _server_cluster_config = {
        INOVELLI_CLUSTER: ClusterConfig(
            attributes={
                name: AttrConfig(read_on_startup=fresh)
                for name, fresh in {
                    "dimming_speed_up_remote": False,
                    "dimming_speed_up_local": False,
                    "ramp_rate_off_to_on_remote": False,
                    "ramp_rate_off_to_on_local": False,
                    "dimming_speed_down_remote": False,
                    "dimming_speed_down_local": False,
                    "ramp_rate_on_to_off_remote": False,
                    "ramp_rate_on_to_off_local": False,
                    "minimum_level": False,
                    "maximum_level": False,
                    "invert_switch": False,
                    "auto_off_timer": False,
                    "default_level_local": False,
                    "default_level_remote": False,
                    "state_after_power_restored": False,
                    "load_level_indicator_timeout": False,
                    "active_power_reports": False,
                    "periodic_power_and_energy_reports": False,
                    "active_energy_reports": False,
                    "power_type": True,
                    "switch_type": True,
                    "internal_temp_monitor": False,
                    "overheated": False,
                    "button_delay": True,
                    "smart_bulb_mode": True,
                    "led_color_when_on": False,
                    "led_color_when_off": False,
                    "led_intensity_when_on": False,
                    "led_intensity_when_off": False,
                    "led_scaling_mode": False,
                    "aux_switch_scenes": False,
                    "binding_off_to_on_sync_level": False,
                    "local_protection": True,
                    "output_mode": True,
                    "firmware_progress_led": False,
                    "disable_clear_notifications_double_tap": False,
                }.items()
            },
        ),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliVzm31Init(VirtualEntity):
    """Inovelli VZM31-SN dimmer attribute init."""

    _unique_id_suffix = "inovelli_vzm31_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM31-SN"}),
    )
    _server_cluster_config = {
        INOVELLI_CLUSTER: ClusterConfig(
            attributes={
                name: AttrConfig(read_on_startup=fresh)
                for name, fresh in {
                    "dimming_speed_up_remote": False,
                    "dimming_speed_up_local": False,
                    "ramp_rate_off_to_on_remote": False,
                    "ramp_rate_off_to_on_local": False,
                    "dimming_speed_down_remote": False,
                    "dimming_speed_down_local": False,
                    "ramp_rate_on_to_off_remote": False,
                    "ramp_rate_on_to_off_local": False,
                    "minimum_level": False,
                    "maximum_level": False,
                    "invert_switch": False,
                    "auto_off_timer": False,
                    "default_level_local": False,
                    "default_level_remote": False,
                    "state_after_power_restored": False,
                    "load_level_indicator_timeout": False,
                    "active_power_reports": False,
                    "periodic_power_and_energy_reports": False,
                    "active_energy_reports": False,
                    "power_type": True,
                    "switch_type": True,
                    "quick_start_time": False,
                    "quick_start_level": False,
                    "increased_non_neutral_output": False,
                    "leading_or_trailing_edge": False,
                    "internal_temp_monitor": False,
                    "overheated": False,
                    "button_delay": True,
                    "smart_bulb_mode": True,
                    "double_tap_up_enabled": False,
                    "double_tap_down_enabled": False,
                    "double_tap_up_level": False,
                    "double_tap_down_level": False,
                    "led_color_when_on": False,
                    "led_color_when_off": False,
                    "led_intensity_when_on": False,
                    "led_intensity_when_off": False,
                    "led_scaling_mode": False,
                    "aux_switch_scenes": False,
                    "binding_off_to_on_sync_level": False,
                    "local_protection": True,
                    "output_mode": True,
                    "on_off_led_mode": False,
                    "firmware_progress_led": False,
                    "relay_click_in_on_off_mode": False,
                    "disable_clear_notifications_double_tap": False,
                }.items()
            },
        ),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliVzm35Init(VirtualEntity):
    """Inovelli VZM35-SN fan switch attribute init."""

    _unique_id_suffix = "inovelli_vzm35_init"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM35-SN"}),
    )
    _server_cluster_config = {
        INOVELLI_CLUSTER: ClusterConfig(
            attributes={
                name: AttrConfig(read_on_startup=fresh)
                for name, fresh in {
                    "dimming_speed_up_remote": False,
                    "dimming_speed_up_local": False,
                    "ramp_rate_off_to_on_local": False,
                    "ramp_rate_off_to_on_remote": False,
                    "dimming_speed_down_remote": False,
                    "dimming_speed_down_local": False,
                    "ramp_rate_on_to_off_local": False,
                    "ramp_rate_on_to_off_remote": False,
                    "minimum_level": False,
                    "maximum_level": False,
                    "invert_switch": False,
                    "auto_off_timer": False,
                    "default_level_local": False,
                    "default_level_remote": False,
                    "state_after_power_restored": False,
                    "load_level_indicator_timeout": False,
                    "power_type": True,
                    "switch_type": True,
                    "non_neutral_aux_med_gear_learn_value": False,
                    "non_neutral_aux_low_gear_learn_value": False,
                    "quick_start_time": True,
                    "button_delay": True,
                    "smart_fan_mode": True,
                    "double_tap_up_enabled": False,
                    "double_tap_down_enabled": False,
                    "double_tap_up_level": False,
                    "double_tap_down_level": False,
                    "led_color_when_on": False,
                    "led_color_when_off": False,
                    "led_intensity_when_on": False,
                    "led_intensity_when_off": False,
                    "aux_switch_scenes": False,
                    "local_protection": True,
                    "output_mode": True,
                    "on_off_led_mode": False,
                    "firmware_progress_led": False,
                    "smart_fan_led_display_levels": False,
                }.items()
            },
        ),
    }
