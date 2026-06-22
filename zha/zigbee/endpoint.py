"""Representation of a Zigbee endpoint for zha."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Final

from zigpy.profiles.zha import PROFILE_ID as ZHA_PROFILE_ID
from zigpy.profiles.zll import PROFILE_ID as ZLL_PROFILE_ID
import zigpy.zcl
from zigpy.zcl.foundation import CommandSchema

from zha.application import const

if TYPE_CHECKING:
    from zigpy.endpoint import Endpoint as ZigpyEndpoint

    from zha.zigbee.device import Device

ATTR_DEVICE_TYPE: Final[str] = "device_type"
ATTR_PROFILE_ID: Final[str] = "profile_id"
ATTR_IN_CLUSTERS: Final[str] = "input_clusters"
ATTR_OUT_CLUSTERS: Final[str] = "output_clusters"

_LOGGER = logging.getLogger(__name__)


def cluster_event_unique_id(endpoint: Endpoint, cluster: zigpy.zcl.Cluster) -> str:
    """Build the `ieee:endpoint_id:0xCLUSTER[_CLIENT]` unique_id for a cluster event."""
    ieee_with_colons = endpoint.unique_id.replace("-", ":")
    suffix = "_CLIENT" if cluster.is_client else ""
    return f"{ieee_with_colons}:0x{cluster.cluster_id:04x}{suffix}"


def split_event_arg(
    command: str, arg: list | dict | CommandSchema | None
) -> tuple[list | dict, dict[str, Any]]:
    """Decompose a cluster-event argument into ZHA event `args`/`params`."""
    if arg is None:
        return [], {}
    if isinstance(arg, CommandSchema):
        return [a for a in arg if a is not None], arg.as_dict()
    if isinstance(arg, (list, dict)):
        return arg, {}
    raise TypeError(f"Unexpected cluster event {command!r} argument: {arg!r}")


class _ClusterEventForwarder:
    """Forwards quirk `zha_send_event` listener calls into device `zha_event`s."""

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        self._cluster = cluster
        self._endpoint = endpoint
        self._unique_id = cluster_event_unique_id(endpoint, cluster)
        cluster.add_listener(self)

    def remove(self) -> None:
        """Detach from the cluster."""
        self._cluster.remove_listener(self)

    def zha_send_event(self, command: str, arg: list | dict | CommandSchema) -> None:
        """Relay events to listeners."""
        args, params = split_event_arg(command, arg)
        self._endpoint.emit_zha_event(
            {
                const.ATTR_UNIQUE_ID: self._unique_id,
                const.ATTR_CLUSTER_ID: self._cluster.cluster_id,
                const.ATTR_COMMAND: command,
                const.ATTR_ARGS: args,
                const.ATTR_PARAMS: params,
            }
        )


class Endpoint:
    """Endpoint for a zha device."""

    def __init__(self, zigpy_endpoint: ZigpyEndpoint, device: Device) -> None:
        """Initialize instance."""
        assert zigpy_endpoint is not None
        assert device is not None
        self._zigpy_endpoint: ZigpyEndpoint = zigpy_endpoint
        self._device: Device = device
        self._unique_id: str = f"{device.unique_id}-{zigpy_endpoint.endpoint_id}"
        self._forwarders: list[_ClusterEventForwarder] = []

    def on_remove(self) -> None:
        """Run when endpoint is removed."""
        for forwarder in self._forwarders:
            forwarder.remove()
        self._forwarders.clear()

    @functools.cached_property
    def device(self) -> Device:
        """Return the device this endpoint belongs to."""
        return self._device

    @functools.cached_property
    def zigpy_endpoint(self) -> ZigpyEndpoint:
        """Return endpoint of zigpy device."""
        return self._zigpy_endpoint

    @functools.cached_property
    def id(self) -> int:
        """Return endpoint id."""
        return self._zigpy_endpoint.endpoint_id

    @functools.cached_property
    def unique_id(self) -> str:
        """Return the unique id for this endpoint."""
        return self._unique_id

    @property
    def zigbee_signature(self) -> tuple[int, dict[str, Any]]:
        """Get the zigbee signature for the endpoint this pool represents."""
        return (
            self.id,
            {
                ATTR_PROFILE_ID: f"0x{self._zigpy_endpoint.profile_id:04x}"
                if self._zigpy_endpoint.profile_id is not None
                else "",
                ATTR_DEVICE_TYPE: f"0x{self._zigpy_endpoint.device_type:04x}"
                if self._zigpy_endpoint.device_type is not None
                else "",
                ATTR_IN_CLUSTERS: [
                    f"0x{cluster_id:04x}"
                    for cluster_id in sorted(self._zigpy_endpoint.in_clusters)
                ],
                ATTR_OUT_CLUSTERS: [
                    f"0x{cluster_id:04x}"
                    for cluster_id in sorted(self._zigpy_endpoint.out_clusters)
                ],
            },
        )

    @classmethod
    def new(cls, zigpy_endpoint: ZigpyEndpoint, device: Device) -> Endpoint:
        """Create new endpoint and attach quirk-event forwarders to each cluster."""
        endpoint = cls(zigpy_endpoint, device)
        endpoint._attach_legacy_event_forwarders()
        return endpoint

    def _attach_legacy_event_forwarders(self) -> None:
        """Attach legacy quirk-event forwarders to every server and client cluster."""
        profile_id = self._zigpy_endpoint.profile_id
        if profile_id is None:
            _LOGGER.debug("Skipping endpoint, profile is None")
            return
        if profile_id not in (ZLL_PROFILE_ID, ZHA_PROFILE_ID):
            _LOGGER.debug(
                "Skipping endpoint, profile is not ZLL or ZHA: 0x%04X", profile_id
            )
            return

        for cluster in (
            *self._zigpy_endpoint.in_clusters.values(),
            *self._zigpy_endpoint.out_clusters.values(),
        ):
            self._forwarders.append(_ClusterEventForwarder(cluster, self))

    def emit_zha_event(self, event_data: dict[str, Any]) -> None:
        """Broadcast an event from this endpoint."""
        self.device.emit_zha_event(
            {
                const.ATTR_UNIQUE_ID: self.unique_id,
                const.ATTR_ENDPOINT_ID: self.id,
                **event_data,
            }
        )
