"""Alarm control panels on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
import functools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.security import (
    AlarmStatus,
    ArmMode,
    ArmNotification,
    IasAce as AceCluster,
    PanelStatus,
)

from zha.application import Platform
from zha.application.platforms import (
    BaseEntityInfo,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.alarm_control_panel.const import (
    IAS_ACE_STATE_MAP,
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_HOME,
    SUPPORT_ALARM_ARM_NIGHT,
    SUPPORT_ALARM_TRIGGER,
    AlarmState,
    CodeFormat,
)
from zha.zigbee.endpoint import cluster_event_unique_id

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)

SIGNAL_ARMED_STATE_CHANGED = "zha_armed_state_changed"
SIGNAL_ALARM_TRIGGERED = "zha_armed_triggered"


@dataclass(frozen=True, kw_only=True)
class AlarmControlPanelEntityInfo(BaseEntityInfo):
    """Alarm control panel entity info."""

    code_arm_required: bool
    code_format: CodeFormat
    supported_features: int
    translation_key: str


class BaseAlarmControlPanel(PlatformEntity, ABC):
    """Abstract base class for ZHA alarm control panel entities."""

    PLATFORM = Platform.ALARM_CONTROL_PANEL

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the alarm control panel."""
        response = super().state
        response["state"] = self.alarm_state
        return response

    @property
    @abstractmethod
    def alarm_state(self) -> AlarmState:
        """Return the current alarm state."""

    @property
    @abstractmethod
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""

    _attr_code_format: CodeFormat
    _attr_supported_features: int

    @property
    def code_format(self) -> CodeFormat:
        """Code format or None if no code is required."""
        return self._attr_code_format

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return self._attr_supported_features

    @functools.cached_property
    def info_object(self) -> AlarmControlPanelEntityInfo:
        """Return a representation of the alarm control panel."""
        return AlarmControlPanelEntityInfo(
            **super().info_object.__dict__,
            code_arm_required=self.code_arm_required,
            code_format=self.code_format,
            supported_features=self.supported_features,
        )

    @abstractmethod
    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""

    @abstractmethod
    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""

    @abstractmethod
    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""

    @abstractmethod
    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""

    @abstractmethod
    async def async_alarm_trigger(self, code: str | None = None) -> None:
        """Send alarm trigger command."""


@register_entity(AceCluster.cluster_id)
class AlarmControlPanel(BaseAlarmControlPanel):
    """Entity for ZHA alarm control devices."""

    _attr_translation_key: str = "alarm_control_panel"
    _attr_code_format = CodeFormat.NUMBER
    _attr_supported_features = (
        SUPPORT_ALARM_ARM_HOME
        | SUPPORT_ALARM_ARM_AWAY
        | SUPPORT_ALARM_ARM_NIGHT
        | SUPPORT_ALARM_TRIGGER
    )

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({AceCluster.cluster_id}),
    )

    _client_cluster_config = {
        AceCluster.cluster_id: ClusterConfig(
            bind=True,
        ),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the ZHA alarm control device."""
        legacy_discovery_unique_id = (
            f"{endpoint.device.ieee}-{endpoint.id}-{int(AceCluster.cluster_id)}"
        )
        super().__init__(
            endpoint=endpoint,
            device=device,
            **kwargs,
            legacy_discovery_unique_id=legacy_discovery_unique_id,
        )

        self._cluster = endpoint.zigpy_endpoint.out_clusters[AceCluster.cluster_id]
        self._cluster_event_unique_id = cluster_event_unique_id(endpoint, self._cluster)

        alarm_options = device.gateway.config.config.alarm_control_panel_options
        self.panel_code: str = alarm_options.master_code
        self.code_required_arm_actions: bool = alarm_options.arm_requires_code
        self.max_invalid_tries: int = alarm_options.failed_tries

        self.armed_state: PanelStatus = AceCluster.PanelStatus.Panel_Disarmed
        self.alarm_status: AlarmStatus = AceCluster.AlarmStatus.No_Alarm
        self.invalid_tries: int = 0

        self._command_map: dict[int, Callable[..., Any]] = {
            AceCluster.ServerCommandDefs.arm.id: self._cmd_arm,
            AceCluster.ServerCommandDefs.bypass.id: self._bypass,
            AceCluster.ServerCommandDefs.emergency.id: self._emergency,
            AceCluster.ServerCommandDefs.fire.id: self._fire,
            AceCluster.ServerCommandDefs.panic.id: self._panic_cmd,
            AceCluster.ServerCommandDefs.get_zone_id_map.id: self._get_zone_id_map,
            AceCluster.ServerCommandDefs.get_zone_info.id: self._get_zone_info,
            AceCluster.ServerCommandDefs.get_panel_status.id: self._send_panel_status_response,
            AceCluster.ServerCommandDefs.get_bypassed_zone_list.id: self._get_bypassed_zone_list,
            AceCluster.ServerCommandDefs.get_zone_status.id: self._get_zone_status,
        }
        self._arm_map: dict[ArmMode, Callable[..., Any]] = {
            AceCluster.ArmMode.Disarm: self._disarm,
            AceCluster.ArmMode.Arm_All_Zones: self._arm_away,
            AceCluster.ArmMode.Arm_Day_Home_Only: self._arm_day,
            AceCluster.ArmMode.Arm_Night_Sleep_Only: self._arm_night,
        }

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._cluster.add_listener(self)
        self._on_remove_callbacks.append(lambda: self._cluster.remove_listener(self))

    def cluster_command(self, tsn: int, command_id: int, args: list[Any]) -> None:
        """Handle commands received on the IAS ACE cluster."""
        self.debug(
            "received command %s", self._cluster.server_commands[command_id].name
        )
        self._command_map[command_id](*args)

    def _emit_zha_event(self, command: str, args: list | dict) -> None:
        """Relay a cluster-level zha_event via the endpoint."""
        self._endpoint.emit_zha_event(
            {
                "unique_id": self._cluster_event_unique_id,
                "cluster_id": self._cluster.cluster_id,
                "command": command,
                "args": args if isinstance(args, list) else [],
                "params": args if isinstance(args, dict) else {},
            }
        )

    def _cmd_arm(self, arm_mode: int, code: str | None, zone_id: int) -> None:
        """Handle the IAS ACE arm command."""
        mode = AceCluster.ArmMode(arm_mode)

        self._emit_zha_event(
            AceCluster.ServerCommandDefs.arm.name,
            {
                "arm_mode": mode.value,
                "arm_mode_description": mode.name,
                "code": code,
                "zone_id": zone_id,
            },
        )

        zigbee_reply = self._arm_map[mode](code)
        self._device.gateway.async_create_task(zigbee_reply)

        if self.invalid_tries >= self.max_invalid_tries:
            self.alarm_status = AceCluster.AlarmStatus.Emergency
            self.armed_state = AceCluster.PanelStatus.In_Alarm
            self._emit_zha_event(
                f"{self._cluster_event_unique_id}_{SIGNAL_ALARM_TRIGGERED}", []
            )
        else:
            self._emit_zha_event(
                f"{self._cluster_event_unique_id}_{SIGNAL_ARMED_STATE_CHANGED}", []
            )
        self._emit_panel_status_changed()

    def _disarm(self, code: str):
        """Test the code and disarm the panel if the code is correct."""
        if (
            code != self.panel_code
            and self.armed_state != AceCluster.PanelStatus.Panel_Disarmed
        ):
            self.debug("Invalid code supplied to IAS ACE")
            self.invalid_tries += 1
            zigbee_reply = self._cluster.arm_response(
                AceCluster.ArmNotification.Invalid_Arm_Disarm_Code
            )
        else:
            self.invalid_tries = 0
            if (
                self.armed_state == AceCluster.PanelStatus.Panel_Disarmed
                and self.alarm_status == AceCluster.AlarmStatus.No_Alarm
            ):
                self.debug("IAS ACE already disarmed")
                zigbee_reply = self._cluster.arm_response(
                    AceCluster.ArmNotification.Already_Disarmed
                )
            else:
                self.debug("Disarming all IAS ACE zones")
                zigbee_reply = self._cluster.arm_response(
                    AceCluster.ArmNotification.All_Zones_Disarmed
                )

            self.armed_state = AceCluster.PanelStatus.Panel_Disarmed
            self.alarm_status = AceCluster.AlarmStatus.No_Alarm
        return zigbee_reply

    def _arm_day(self, code: str):
        """Arm the panel for day / home zones."""
        return self._handle_arm(
            code,
            AceCluster.PanelStatus.Armed_Stay,
            AceCluster.ArmNotification.Only_Day_Home_Zones_Armed,
        )

    def _arm_night(self, code: str):
        """Arm the panel for night / sleep zones."""
        return self._handle_arm(
            code,
            AceCluster.PanelStatus.Armed_Night,
            AceCluster.ArmNotification.Only_Night_Sleep_Zones_Armed,
        )

    def _arm_away(self, code: str):
        """Arm the panel for away mode."""
        return self._handle_arm(
            code,
            AceCluster.PanelStatus.Armed_Away,
            AceCluster.ArmNotification.All_Zones_Armed,
        )

    def _handle_arm(
        self,
        code: str,
        panel_status: PanelStatus,
        armed_type: ArmNotification,
    ):
        """Arm the panel with the specified statuses."""
        if self.code_required_arm_actions and code != self.panel_code:
            self.debug("Invalid code supplied to IAS ACE")
            zigbee_reply = self._cluster.arm_response(
                AceCluster.ArmNotification.Invalid_Arm_Disarm_Code
            )
        else:
            self.debug("Arming all IAS ACE zones")
            self.armed_state = panel_status
            zigbee_reply = self._cluster.arm_response(armed_type)
        return zigbee_reply

    def _bypass(self, zone_list, code) -> None:
        """Handle the IAS ACE bypass command."""
        self._emit_zha_event(
            AceCluster.ServerCommandDefs.bypass.name,
            {"zone_list": zone_list, "code": code},
        )

    def _emergency(self) -> None:
        """Handle the IAS ACE emergency command."""
        self._set_alarm(AceCluster.AlarmStatus.Emergency)

    def _fire(self) -> None:
        """Handle the IAS ACE fire command."""
        self._set_alarm(AceCluster.AlarmStatus.Fire)

    def _panic_cmd(self) -> None:
        """Handle the IAS ACE panic command (received from device)."""
        self._set_alarm(AceCluster.AlarmStatus.Emergency_Panic)

    def _set_alarm(self, status: AlarmStatus) -> None:
        """Set the specified alarm status."""
        self.alarm_status = status
        self.armed_state = AceCluster.PanelStatus.In_Alarm
        self._emit_panel_status_changed()

    def _get_zone_id_map(self):
        """Handle the IAS ACE zone id map command."""

    def _get_zone_info(self, zone_id):
        """Handle the IAS ACE zone info command."""

    def _send_panel_status_response(self) -> None:
        """Handle the IAS ACE panel status response command."""
        response = self._cluster.panel_status_response(
            self.armed_state,
            0x00,
            AceCluster.AudibleNotification.Default_Sound,
            self.alarm_status,
        )
        self._device.gateway.async_create_task(response)

    def _emit_panel_status_changed(self) -> None:
        """Handle the IAS ACE panel status changed command."""
        response = self._cluster.panel_status_changed(
            self.armed_state,
            0x00,
            AceCluster.AudibleNotification.Default_Sound,
            self.alarm_status,
        )
        self._device.gateway.async_create_task(response)
        self.maybe_emit_state_changed_event()

    def _get_bypassed_zone_list(self):
        """Handle the IAS ACE bypassed zone list command."""

    def _get_zone_status(
        self, starting_zone_id, max_zone_ids, zone_status_mask_flag, zone_status_mask
    ):
        """Handle the IAS ACE zone status command."""

    @property
    def alarm_state(self) -> AlarmState:
        """Return the current alarm state."""
        return IAS_ACE_STATE_MAP.get(self.armed_state, AlarmState.UNKNOWN)

    @property
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""
        return self.code_required_arm_actions

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        self._cmd_arm(AceCluster.ArmMode.Disarm, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        self._cmd_arm(AceCluster.ArmMode.Arm_Day_Home_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        self._cmd_arm(AceCluster.ArmMode.Arm_All_Zones, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""
        self._cmd_arm(AceCluster.ArmMode.Arm_Night_Sleep_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_trigger(self, code: str | None = None) -> None:  # pylint: disable=unused-argument
        """Send alarm trigger command."""
        self._panic_cmd()
        self.maybe_emit_state_changed_event()
