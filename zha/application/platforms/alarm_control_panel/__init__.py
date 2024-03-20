"""Alarm control panels on Zigbee Home Automation networks."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from zigpy.zcl.clusters.security import IasAce

from zha.application import Platform
from zha.application.const import (
    CONF_ALARM_ARM_REQUIRES_CODE,
    CONF_ALARM_FAILED_TRIES,
    CONF_ALARM_MASTER_CODE,
    ZHA_ALARM_OPTIONS,
)
from zha.application.helpers import async_get_zha_config_value
from zha.application.platforms import PlatformEntity
from zha.application.platforms.alarm_control_panel.const import (
    IAS_ACE_STATE_MAP,
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_HOME,
    SUPPORT_ALARM_ARM_NIGHT,
    SUPPORT_ALARM_TRIGGER,
    AlarmState,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_IAS_ACE,
)
from zha.zigbee.cluster_handlers.security import (
    ClusterHandlerStateChangedEvent,
    IasAceClusterHandler,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(
    PLATFORM_ENTITIES.strict_match, Platform.ALARM_CONTROL_PANEL
)

_LOGGER = logging.getLogger(__name__)


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_IAS_ACE)
class ZHAAlarmControlPanel(PlatformEntity):
    """Entity for ZHA alarm control devices."""

    PLATFORM = Platform.ALARM_CONTROL_PANEL

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ) -> None:
        """Initialize the ZHA alarm control device."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        config = device.gateway.config
        self._cluster_handler: IasAceClusterHandler = cluster_handlers[0]
        self._cluster_handler.panel_code = async_get_zha_config_value(
            config, ZHA_ALARM_OPTIONS, CONF_ALARM_MASTER_CODE, "1234"
        )
        self._cluster_handler.code_required_arm_actions = async_get_zha_config_value(
            config, ZHA_ALARM_OPTIONS, CONF_ALARM_ARM_REQUIRES_CODE, False
        )
        self._cluster_handler.max_invalid_tries = async_get_zha_config_value(
            config, ZHA_ALARM_OPTIONS, CONF_ALARM_FAILED_TRIES, 3
        )
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    def handle_cluster_handler_state_changed(
        self,
        event: ClusterHandlerStateChangedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state changed on cluster."""
        self.maybe_send_state_changed_event()

    def async_set_armed_mode(self) -> None:
        """Set the entity state."""
        self.maybe_send_state_changed_event()

    @property
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""
        return self._cluster_handler.code_required_arm_actions

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        self._cluster_handler.arm(IasAce.ArmMode.Disarm, code, 0)
        self.maybe_send_state_changed_event()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Day_Home_Only, code, 0)
        self.maybe_send_state_changed_event()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_All_Zones, code, 0)
        self.maybe_send_state_changed_event()

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Night_Sleep_Only, code, 0)
        self.maybe_send_state_changed_event()

    async def async_alarm_trigger(self, code: str | None = None) -> None:  # pylint: disable=unused-argument
        """Send alarm trigger command."""
        self._cluster_handler.panic()
        self.maybe_send_state_changed_event()

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            SUPPORT_ALARM_ARM_HOME
            | SUPPORT_ALARM_ARM_AWAY
            | SUPPORT_ALARM_ARM_NIGHT
            | SUPPORT_ALARM_TRIGGER
        )

    @property
    def state(self) -> str:
        """Return the state of the entity."""
        return IAS_ACE_STATE_MAP.get(
            self._cluster_handler.armed_state, AlarmState.UNKNOWN
        )

    def get_state(self) -> dict:
        """Get the state of the alarm control panel."""
        response = super().get_state()
        response["state"] = self.state
        return response
