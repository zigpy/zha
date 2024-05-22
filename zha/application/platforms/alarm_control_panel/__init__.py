"""Alarm control panels on Zigbee Home Automation networks."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.security import IasAce

from zha.application import Platform
from zha.application.platforms import PlatformEntity, PlatformEntityInfo
from zha.application.platforms.alarm_control_panel.const import (
    IAS_ACE_STATE_MAP,
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_HOME,
    SUPPORT_ALARM_ARM_NIGHT,
    SUPPORT_ALARM_TRIGGER,
    AlarmState,
    CodeFormat,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_IAS_ACE,
    CLUSTER_HANDLER_STATE_CHANGED,
)
from zha.zigbee.cluster_handlers.security import (
    ClusterHandlerStateChangedEvent,
    IasAceClusterHandler,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(
    PLATFORM_ENTITIES.strict_match, Platform.ALARM_CONTROL_PANEL
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AlarmControlPanelEntityInfo(PlatformEntityInfo):
    """Alarm control panel entity info."""

    code_arm_required: bool
    code_format: CodeFormat
    supported_features: int
    translation_key: str


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_IAS_ACE)
class AlarmControlPanel(PlatformEntity):
    """Entity for ZHA alarm control devices."""

    _attr_translation_key: str = "alarm_control_panel"
    PLATFORM = Platform.ALARM_CONTROL_PANEL

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the ZHA alarm control device."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        alarm_options = device.gateway.config.config.alarm_control_panel_options
        self._cluster_handler: IasAceClusterHandler = cluster_handlers[0]
        self._cluster_handler.panel_code = alarm_options.master_code
        self._cluster_handler.code_required_arm_actions = (
            alarm_options.arm_requires_code
        )
        self._cluster_handler.max_invalid_tries = alarm_options.failed_tries
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_STATE_CHANGED, self._handle_event_protocol
        )

    @functools.cached_property
    def info_object(self) -> AlarmControlPanelEntityInfo:
        """Return a representation of the alarm control panel."""
        return AlarmControlPanelEntityInfo(
            **super().info_object.__dict__,
            code_arm_required=self.code_arm_required,
            code_format=self.code_format,
            supported_features=self.supported_features,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the alarm control panel."""
        response = super().state
        response["state"] = IAS_ACE_STATE_MAP.get(
            self._cluster_handler.armed_state, AlarmState.UNKNOWN
        )
        return response

    @property
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""
        return self._cluster_handler.code_required_arm_actions

    @functools.cached_property
    def code_format(self) -> CodeFormat:
        """Code format or None if no code is required."""
        return CodeFormat.NUMBER

    @functools.cached_property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            SUPPORT_ALARM_ARM_HOME
            | SUPPORT_ALARM_ARM_AWAY
            | SUPPORT_ALARM_ARM_NIGHT
            | SUPPORT_ALARM_TRIGGER
        )

    def handle_cluster_handler_state_changed(
        self,
        event: ClusterHandlerStateChangedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state changed on cluster."""
        self.maybe_emit_state_changed_event()

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        self._cluster_handler.arm(IasAce.ArmMode.Disarm, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Day_Home_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_All_Zones, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Night_Sleep_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_trigger(self, code: str | None = None) -> None:  # pylint: disable=unused-argument
        """Send alarm trigger command."""
        self._cluster_handler.panic()
        self.maybe_emit_state_changed_event()
