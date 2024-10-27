"""Alarm control panels on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
import functools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.security import IasAce

from zha.application import Platform
from zha.application.platforms import PlatformEntity, WebSocketClientEntity
from zha.application.platforms.alarm_control_panel.const import (
    IAS_ACE_STATE_MAP,
    AlarmControlPanelEntityFeature,
    AlarmState,
    CodeFormat,
)
from zha.application.platforms.alarm_control_panel.model import (
    AlarmControlPanelEntityInfo,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_IAS_ACE,
    CLUSTER_HANDLER_STATE_CHANGED,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.cluster_handlers.security import (
        ClusterHandlerStateChangedEvent,
        IasAceClusterHandler,
    )
    from zha.zigbee.device import Device, WebSocketClientDevice
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(
    PLATFORM_ENTITIES.strict_match, Platform.ALARM_CONTROL_PANEL
)

_LOGGER = logging.getLogger(__name__)


class AlarmControlPanelEntityInterface(ABC):
    """Base class for alarm control panels."""

    @property
    @abstractmethod
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""

    @functools.cached_property
    @abstractmethod
    def code_format(self) -> CodeFormat:
        """Code format or None if no code is required."""

    @functools.cached_property
    @abstractmethod
    def supported_features(self) -> int:
        """Return the list of supported features."""

    @abstractmethod
    async def async_alarm_disarm(self, code: str | None = None, **kwargs) -> None:
        """Send disarm command."""

    @abstractmethod
    async def async_alarm_arm_home(self, code: str | None = None, **kwargs) -> None:
        """Send arm home command."""

    @abstractmethod
    async def async_alarm_arm_away(self, code: str | None = None, **kwargs) -> None:
        """Send arm away command."""

    @abstractmethod
    async def async_alarm_arm_night(self, code: str | None = None, **kwargs) -> None:
        """Send arm night command."""

    @abstractmethod
    async def async_alarm_trigger(self, code: str | None = None, **kwargs) -> None:
        """Send alarm trigger command."""


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_IAS_ACE)
class AlarmControlPanel(PlatformEntity, AlarmControlPanelEntityInterface):
    """Entity for ZHA alarm control devices."""

    PLATFORM = Platform.ALARM_CONTROL_PANEL
    _attr_translation_key: str = "alarm_control_panel"

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
            max_invalid_tries=self._cluster_handler.max_invalid_tries,
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
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Return the list of supported features."""
        return (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.TRIGGER
        )

    def handle_cluster_handler_state_changed(
        self,
        event: ClusterHandlerStateChangedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state changed on cluster."""
        self.maybe_emit_state_changed_event()

    async def async_alarm_disarm(self, code: str | None = None, **kwargs) -> None:
        """Send disarm command."""
        self._cluster_handler.arm(IasAce.ArmMode.Disarm, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_home(self, code: str | None = None, **kwargs) -> None:
        """Send arm home command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Day_Home_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_away(self, code: str | None = None, **kwargs) -> None:
        """Send arm away command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_All_Zones, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_arm_night(self, code: str | None = None, **kwargs) -> None:
        """Send arm night command."""
        self._cluster_handler.arm(IasAce.ArmMode.Arm_Night_Sleep_Only, code, 0)
        self.maybe_emit_state_changed_event()

    async def async_alarm_trigger(self, code: str | None = None, **kwargs) -> None:  # pylint: disable=unused-argument
        """Send alarm trigger command."""
        self._cluster_handler.panic()
        self.maybe_emit_state_changed_event()


class WebSocketClientAlarmControlPanel(
    WebSocketClientEntity, AlarmControlPanelEntityInterface
):
    """Alarm control panel entity for the WebSocket API."""

    PLATFORM = Platform.ALARM_CONTROL_PANEL
    _attr_translation_key: str = "alarm_control_panel"

    def __init__(
        self, entity_info: AlarmControlPanelEntityInfo, device: WebSocketClientDevice
    ) -> None:
        """Initialize the ZHA alarm control device."""
        super().__init__(entity_info)
        self._device: WebSocketClientDevice = device

    @functools.cached_property
    def info_object(self) -> AlarmControlPanelEntityInfo:
        """Return a representation of the alarm control panel."""
        return self._entity_info

    @property
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""
        return self._entity_info.code_arm_required

    @functools.cached_property
    def code_format(self) -> CodeFormat:
        """Code format or None if no code is required."""
        return self._entity_info.code_format

    @functools.cached_property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return self._entity_info.supported_features

    async def async_alarm_disarm(self, code: str | None = None, **kwargs) -> None:
        """Send disarm command."""
        await self._device.gateway.alarm_control_panels.disarm(self._entity_info, code)

    async def async_alarm_arm_home(self, code: str | None = None, **kwargs) -> None:
        """Send arm home command."""
        await self._device.gateway.alarm_control_panels.arm_home(
            self._entity_info, code
        )

    async def async_alarm_arm_away(self, code: str | None = None, **kwargs) -> None:
        """Send arm away command."""
        await self._device.gateway.alarm_control_panels.arm_away(
            self._entity_info, code
        )

    async def async_alarm_arm_night(self, code: str | None = None, **kwargs) -> None:
        """Send arm night command."""
        await self._device.gateway.alarm_control_panels.arm_night(
            self._entity_info, code
        )

    async def async_alarm_trigger(self, code: str | None = None, **kwargs) -> None:
        """Send alarm trigger command."""
        await self._device.gateway.alarm_control_panels.trigger(self._entity_info)
