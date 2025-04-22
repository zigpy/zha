"""Cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Iterator
import contextlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import functools
import logging
from typing import TYPE_CHECKING, Any, Final, ParamSpec, TypedDict

import zigpy.exceptions
import zigpy.util
import zigpy.zcl
from zigpy.zcl.foundation import (
    CommandSchema,
    ConfigureReportingResponseRecord,
    Status,
    ZCLAttributeDef,
)

from zha.application.const import (
    ZHA_CLUSTER_HANDLER_MSG,
    ZHA_CLUSTER_HANDLER_MSG_BIND,
    ZHA_CLUSTER_HANDLER_MSG_CFG_RPT,
)
from zha.application.helpers import safe_read
from zha.event import EventBase
from zha.exceptions import ZHAException
from zha.mixins import LogMixin
from zha.zigbee.cluster_handlers.const import (
    ARGS,
    ATTRIBUTE_ID,
    ATTRIBUTE_NAME,
    ATTRIBUTE_VALUE,
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_ZDO,
    CLUSTER_ID,
    CLUSTER_READS_PER_REQ,
    COMMAND,
    PARAMS,
    REPORT_CONFIG_ATTR_PER_REQ,
    SIGNAL_ATTR_UPDATED,
    UNIQUE_ID,
    VALUE,
)

if TYPE_CHECKING:
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)
RETRYABLE_REQUEST_DECORATOR = zigpy.util.retryable_request(tries=3)
UNPROXIED_CLUSTER_METHODS = {"general_command"}


_P = ParamSpec("_P")
_FuncType = Callable[_P, Awaitable[Any]]
_ReturnFuncType = Callable[_P, Coroutine[Any, Any, Any]]


@contextlib.contextmanager
def wrap_zigpy_exceptions() -> Iterator[None]:
    """Wrap zigpy exceptions in `ZHAException` exceptions."""
    try:
        yield
    except TimeoutError as exc:
        raise ZHAException("Failed to send request: device did not respond") from exc
    except zigpy.exceptions.ZigbeeException as exc:
        message = "Failed to send request"

        if str(exc):
            message = f"{message}: {exc}"

        raise ZHAException(message) from exc


def retry_request(func: _FuncType[_P]) -> _ReturnFuncType[_P]:
    """Send a request with retries and wrap expected zigpy exceptions."""

    @functools.wraps(func)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
        with wrap_zigpy_exceptions():
            return await RETRYABLE_REQUEST_DECORATOR(func)(*args, **kwargs)

    return wrapper


class AttrReportConfig(TypedDict, total=True):
    """Configuration to report for the attributes."""

    # An attribute name
    attr: str
    # The config for the attribute reporting configuration consists of a tuple for
    # (minimum_reported_time_interval_s, maximum_reported_time_interval_s, value_delta)
    config: tuple[int, int, int | float]


def parse_and_log_command(cluster_handler, tsn, command_id, args):
    """Parse and log a zigbee cluster command."""
    try:
        name = cluster_handler.cluster.server_commands[command_id].name
    except KeyError:
        name = f"0x{command_id:02X}"

    cluster_handler.debug(
        "received '%s' command with %s args on cluster_id '%s' tsn '%s'",
        name,
        args,
        cluster_handler.cluster.cluster_id,
        tsn,
    )
    return name


class ClusterHandlerStatus(Enum):
    """Status of a cluster handler."""

    CREATED = 1
    CONFIGURED = 2
    INITIALIZED = 3


@dataclass(kw_only=True, frozen=True)
class ClusterAttributeUpdatedEvent:
    """Event to signal that a cluster attribute has been updated."""

    attribute_id: int
    attribute_name: str
    attribute_value: Any
    cluster_handler_unique_id: str
    cluster_id: int
    event_type: Final[str] = CLUSTER_HANDLER_EVENT
    event: Final[str] = CLUSTER_HANDLER_ATTRIBUTE_UPDATED


@dataclass(kw_only=True, frozen=True)
class ClusterBindEvent:
    """Event generated when the cluster is bound."""

    cluster_name: str
    cluster_id: int
    success: bool
    cluster_handler_unique_id: str
    event_type: Final[str] = ZHA_CLUSTER_HANDLER_MSG
    event: Final[str] = ZHA_CLUSTER_HANDLER_MSG_BIND


@dataclass(kw_only=True, frozen=True)
class ClusterConfigureReportingEvent:
    """Event generates when a cluster configures attribute reporting."""

    cluster_name: str
    cluster_id: int
    attributes: dict[str, dict[str, Any]]
    cluster_handler_unique_id: str
    event_type: Final[str] = ZHA_CLUSTER_HANDLER_MSG
    event: Final[str] = ZHA_CLUSTER_HANDLER_MSG_CFG_RPT


@dataclass(kw_only=True, frozen=True)
class ClusterInfo:
    """Cluster information."""

    id: int
    name: str
    type: str
    commands: dict[int, str]


@dataclass(kw_only=True, frozen=True)
class ClusterHandlerInfo:
    """Cluster handler information."""

    class_name: str
    generic_id: str
    endpoint_id: str
    cluster: ClusterInfo
    id: str
    unique_id: str
    status: ClusterHandlerStatus
    value_attribute: str | None = None


class ClusterHandler(LogMixin, EventBase):
    """Base cluster handler for a Zigbee cluster."""

    REPORT_CONFIG: tuple[AttrReportConfig, ...] = ()
    BIND: bool = True

    # Dict of attributes to read on cluster handler initialization.
    # Dict keys -- attribute ID or names, with bool value indicating whether a cached
    # attribute read is acceptable.
    ZCL_INIT_ATTRS: dict[str, bool] = {}

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize ClusterHandler."""
        super().__init__()
        self._generic_id = f"cluster_handler_0x{cluster.cluster_id:04x}"
        self._endpoint: Endpoint = endpoint
        self._cluster: zigpy.zcl.Cluster = cluster
        self._id: str = f"{endpoint.id}:0x{cluster.cluster_id:04x}"
        unique_id: str = endpoint.unique_id.replace("-", ":")
        self._unique_id: str = f"{unique_id}:0x{cluster.cluster_id:04x}"
        if not hasattr(self, "_value_attribute") and self.REPORT_CONFIG:
            attr_def: ZCLAttributeDef = self.cluster.attributes_by_name[
                self.REPORT_CONFIG[0]["attr"]
            ]
            self.value_attribute = attr_def.name
        self._status: ClusterHandlerStatus = ClusterHandlerStatus.CREATED
        self.data_cache: dict[str, Any] = {}

    def on_add(self) -> None:
        """Call when cluster handler is added."""
        self._cluster.add_listener(self)

    def on_remove(self) -> None:
        """Call when cluster handler will be removed."""
        self._cluster.remove_listener(self)

    @classmethod
    def matches(cls, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> bool:  # pylint: disable=unused-argument
        """Filter the cluster match for specific devices."""
        return True

    @functools.cached_property
    def info_object(self) -> ClusterHandlerInfo:
        """Return info about this cluster handler."""
        return ClusterHandlerInfo(
            class_name=self.__class__.__name__,
            generic_id=self._generic_id,
            endpoint_id=self._endpoint.id,
            cluster=ClusterInfo(
                id=self._cluster.cluster_id,
                name=self._cluster.name,
                type="client" if self._cluster.is_client else "server",
                commands=self._cluster.commands,
            ),
            id=self._id,
            unique_id=self._unique_id,
            status=self._status.name,
            value_attribute=getattr(self, "value_attribute", None),
        )

    @functools.cached_property
    def id(self) -> str:
        """Return cluster handler id unique for this device only."""
        return self._id

    @functools.cached_property
    def generic_id(self) -> str:
        """Return the generic id for this cluster handler."""
        return self._generic_id

    @functools.cached_property
    def unique_id(self) -> str:
        """Return the unique id for this cluster handler."""
        return self._unique_id

    @functools.cached_property
    def cluster(self) -> zigpy.zcl.Cluster:
        """Return the zigpy cluster for this cluster handler."""
        return self._cluster

    @functools.cached_property
    def name(self) -> str:
        """Return friendly name."""
        return self.cluster.ep_attribute or self._generic_id

    @property
    def status(self) -> ClusterHandlerStatus:
        """Return the status of the cluster handler."""
        return self._status

    def __hash__(self) -> int:
        """Make this a hashable."""
        return hash(self._unique_id)

    async def bind(self) -> None:
        """Bind a zigbee cluster.

        This also swallows ZigbeeException exceptions that are thrown when
        devices are unreachable.
        """
        try:
            res = await self.cluster.bind()
            self.debug("bound '%s' cluster: %s", self.cluster.ep_attribute, res[0])
            self._endpoint.device.emit(
                ZHA_CLUSTER_HANDLER_MSG_BIND,
                ClusterBindEvent(
                    cluster_name=self.cluster.name,
                    cluster_id=self.cluster.cluster_id,
                    cluster_handler_unique_id=self.unique_id,
                    success=res[0] == 0,
                ),
            )
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
            self.debug(
                "Failed to bind '%s' cluster: %s",
                self.cluster.ep_attribute,
                str(ex),
                exc_info=ex,
            )
            self._endpoint.device.emit(
                ZHA_CLUSTER_HANDLER_MSG_BIND,
                ClusterBindEvent(
                    cluster_name=self.cluster.name,
                    cluster_id=self.cluster.cluster_id,
                    cluster_handler_unique_id=self.unique_id,
                    success=False,
                ),
            )

    async def configure_reporting(self) -> None:
        """Configure attribute reporting for a cluster.

        This also swallows ZigbeeException exceptions that are thrown when
        devices are unreachable.
        """
        event_data = {}
        kwargs = {}
        if (
            self.cluster.cluster_id >= 0xFC00
            and self._endpoint.device.manufacturer_code
        ):
            kwargs["manufacturer"] = self._endpoint.device.manufacturer_code

        for attr_report in self.REPORT_CONFIG:
            attr, config = attr_report["attr"], attr_report["config"]

            try:
                attr_name = self.cluster.find_attribute(attr).name
            except KeyError:
                attr_name = attr

            event_data[attr_name] = {
                "min": config[0],
                "max": config[1],
                "id": attr,
                "name": attr_name,
                "change": config[2],
                "status": None,
            }

        to_configure = [*self.REPORT_CONFIG]
        chunk, rest = (
            to_configure[:REPORT_CONFIG_ATTR_PER_REQ],
            to_configure[REPORT_CONFIG_ATTR_PER_REQ:],
        )
        while chunk:
            reports = {rec["attr"]: rec["config"] for rec in chunk}
            try:
                res = await self.cluster.configure_reporting_multiple(reports, **kwargs)
                self._configure_reporting_status(reports, res[0], event_data)
            except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
                self.debug(
                    "failed to set reporting on '%s' cluster for: %s",
                    self.cluster.ep_attribute,
                    str(ex),
                )
                break
            chunk, rest = (
                rest[:REPORT_CONFIG_ATTR_PER_REQ],
                rest[REPORT_CONFIG_ATTR_PER_REQ:],
            )

        self._endpoint.device.emit(
            ZHA_CLUSTER_HANDLER_MSG_CFG_RPT,
            ClusterConfigureReportingEvent(
                cluster_name=self.cluster.name,
                cluster_id=self.cluster.cluster_id,
                cluster_handler_unique_id=self.unique_id,
                attributes=event_data,
            ),
        )

    def _configure_reporting_status(
        self,
        attrs: dict[str, tuple[int, int, float | int]],
        res: list | tuple,
        event_data: dict[str, dict[str, Any]],
    ) -> None:
        """Parse configure reporting result."""
        if isinstance(res, (Exception, ConfigureReportingResponseRecord)):
            # assume default response
            self.debug(
                "attr reporting for '%s' on '%s': %s",
                attrs,
                self.name,
                res,
            )
            for attr in attrs:
                event_data[attr]["status"] = Status.FAILURE.name
            return
        if res[0].status == Status.SUCCESS and len(res) == 1:
            self.debug(
                "Successfully configured reporting for '%s' on '%s' cluster: %s",
                attrs,
                self.name,
                res,
            )
            # 2.5.8.1.3 Status Field
            # The status field specifies the status of the Configure Reporting operation attempted on this attribute,
            # as detailed in 2.5.7.3. Note that attribute status records are not included for successfully configured
            # attributes, in order to save bandwidth. In the case of successful configuration of all attributes,
            # only a single attribute status record SHALL be included in the command, with the status field set to
            # SUCCESS and the direction and attribute identifier fields omitted.
            for attr in attrs:
                event_data[attr]["status"] = Status.SUCCESS.name
            return

        for record in res:
            event_data[self.cluster.find_attribute(record.attrid).name]["status"] = (
                record.status.name
            )
        failed = [
            self.cluster.find_attribute(record.attrid).name
            for record in res
            if record.status != Status.SUCCESS
        ]
        self.debug(
            "Failed to configure reporting for '%s' on '%s' cluster: %s",
            failed,
            self.name,
            res,
        )
        success = set(attrs) - set(failed)
        self.debug(
            "Successfully configured reporting for '%s' on '%s' cluster",
            set(attrs) - set(failed),
            self.name,
        )
        for attr in success:
            event_data[attr]["status"] = Status.SUCCESS.name

    async def async_configure(self) -> None:
        """Set cluster binding and attribute reporting."""
        if not self._endpoint.device.skip_configuration:
            if self.BIND:
                self.debug("Performing cluster binding")
                await self.bind()
            if self.cluster.is_server:
                self.debug("Configuring cluster attribute reporting")
                await self.configure_reporting()
            ch_specific_cfg = getattr(
                self, "async_configure_cluster_handler_specific", None
            )
            if ch_specific_cfg:
                self.debug("Performing cluster handler specific configuration")
                await ch_specific_cfg()
            self.debug("finished cluster handler configuration")
        else:
            self.debug("skipping cluster handler configuration")
        self._status = ClusterHandlerStatus.CONFIGURED

    async def async_initialize(self, from_cache: bool) -> None:
        """Initialize cluster handler."""
        if not from_cache and self._endpoint.device.skip_configuration:
            self.debug("Skipping cluster handler initialization")
            self._status = ClusterHandlerStatus.INITIALIZED
            return

        self.debug("initializing cluster handler: from_cache: %s", from_cache)
        cached = [a for a, cached in self.ZCL_INIT_ATTRS.items() if cached]
        uncached = [a for a, cached in self.ZCL_INIT_ATTRS.items() if not cached]
        uncached.extend([cfg["attr"] for cfg in self.REPORT_CONFIG])

        if cached:
            self.debug("initializing cached cluster handler attributes: %s", cached)
            await self._get_attributes(
                True, cached, from_cache=True, only_cache=from_cache
            )
        if uncached:
            self.debug(
                "initializing uncached cluster handler attributes: %s - from cache[%s]",
                uncached,
                from_cache,
            )
            await self._get_attributes(
                True, uncached, from_cache=from_cache, only_cache=from_cache
            )

        ch_specific_init = getattr(
            self, "async_initialize_cluster_handler_specific", None
        )
        if ch_specific_init:
            self.debug(
                "Performing cluster handler specific initialization: %s", uncached
            )
            await ch_specific_init(from_cache=from_cache)

        self.debug("finished cluster handler initialization")
        self._status = ClusterHandlerStatus.INITIALIZED

    def cluster_command(self, tsn, command_id, args) -> None:
        """Handle commands received to this cluster."""

    def attribute_updated(self, attrid: int, value: Any, timestamp: datetime) -> None:
        """Handle attribute updates on this cluster."""
        attr_name = self._get_attribute_name(attrid)
        self.debug(
            "cluster_handler[%s] attribute_updated - cluster[%s] attr[%s] value[%s]",
            self.name,
            self.cluster.name,
            attr_name,
            value,
        )
        self.emit(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            ClusterAttributeUpdatedEvent(
                attribute_id=attrid,
                attribute_name=attr_name,
                attribute_value=value,
                cluster_handler_unique_id=self.unique_id,
                cluster_id=self.cluster.cluster_id,
            ),
        )

    def zdo_command(self, *args, **kwargs) -> None:
        """Handle ZDO commands on this cluster."""

    def zha_send_event(self, command: str, arg: list | dict | CommandSchema) -> None:
        """Compatibility method for emitting ZHA events from quirks until they are updated."""
        self.emit_zha_event(command, arg)

    def emit_zha_event(self, command: str, arg: list | dict | CommandSchema) -> None:
        """Relay events to listeners."""

        args: list | dict
        if isinstance(arg, CommandSchema):
            args = [a for a in arg if a is not None]
            params = arg.as_dict()
        elif isinstance(arg, (list, dict)):
            # Quirks can directly send lists and dicts to ZHA this way
            args = arg
            params = {}
        else:
            raise TypeError(f"Unexpected emit_zha_event {command!r} argument: {arg!r}")

        self._endpoint.emit_zha_event(
            {
                UNIQUE_ID: self.unique_id,
                CLUSTER_ID: self.cluster.cluster_id,
                COMMAND: command,
                # Maintain backwards compatibility with the old zigpy response format
                ARGS: args,
                PARAMS: params,
            }
        )

    async def async_update(self) -> None:
        """Retrieve latest state from cluster."""

    def _get_attribute_name(self, attrid: int) -> str | int:
        if attrid not in self.cluster.attributes:
            return attrid

        return self.cluster.attributes[attrid].name

    async def get_attribute_value(self, attribute, from_cache=True) -> Any:
        """Get the value for an attribute."""
        manufacturer = None
        manufacturer_code = self._endpoint.device.manufacturer_code
        if self.cluster.cluster_id >= 0xFC00 and manufacturer_code:
            manufacturer = manufacturer_code
        result = await safe_read(
            self._cluster,
            [attribute],
            allow_cache=from_cache,
            only_cache=from_cache,
            manufacturer=manufacturer,
        )
        return result.get(attribute)

    async def _get_attributes(
        self,
        raise_exceptions: bool,
        attributes: list[str],
        from_cache: bool = True,
        only_cache: bool = True,
    ) -> dict[int | str, Any]:
        """Get the values for a list of attributes."""
        manufacturer = None
        manufacturer_code = self._endpoint.device.manufacturer_code
        if self.cluster.cluster_id >= 0xFC00 and manufacturer_code:
            manufacturer = manufacturer_code
        chunk = attributes[:CLUSTER_READS_PER_REQ]
        rest = attributes[CLUSTER_READS_PER_REQ:]
        result = {}
        while chunk:
            try:
                self.debug("Reading attributes in chunks: %s", chunk)
                read, _ = await self.cluster.read_attributes(
                    chunk,
                    allow_cache=from_cache,
                    only_cache=only_cache,
                    manufacturer=manufacturer,
                )
                self.debug("Got attributes: %s", read)
                result.update(read)
            except (TimeoutError, zigpy.exceptions.ZigbeeException) as ex:
                self.debug(
                    "failed to get attributes '%s' on '%s' cluster: %s",
                    chunk,
                    self.cluster.ep_attribute,
                    str(ex),
                )
                if raise_exceptions:
                    raise
            chunk = rest[:CLUSTER_READS_PER_REQ]
            rest = rest[CLUSTER_READS_PER_REQ:]
        return result

    async def get_attributes(
        self,
        attributes: list[str],
        from_cache: bool = True,
        only_cache: bool = True,
    ) -> dict[int | str, Any]:
        """Get the values for a list of attributes and raise no exceptions."""
        return await self._get_attributes(False, attributes, from_cache, only_cache)

    async def write_attributes_safe(
        self, attributes: dict[str, Any], manufacturer: int | None = None
    ) -> None:
        """Wrap `write_attributes` to throw an exception on attribute write failure."""

        res = await self.write_attributes(attributes, manufacturer=manufacturer)
        for record in res[0]:
            if record.status != Status.SUCCESS:
                try:
                    name = self.cluster.attributes[record.attrid].name
                    value = attributes.get(name, "unknown")
                except KeyError:
                    name = f"0x{record.attrid:04x}"
                    value = "unknown"

                raise ZHAException(
                    f"Failed to write attribute {name}={value}: {record.status}",
                )

    def log(self, level, msg, *args, **kwargs) -> None:
        """Log a message."""
        msg = f"[%s:%s]: {msg}"
        args = (self._endpoint.device.nwk, self._id) + args
        _LOGGER.log(level, msg, *args, stacklevel=3, **kwargs)

    def __getattr__(self, name):
        """Get attribute or a decorated cluster command."""
        if (
            hasattr(self._cluster, name)
            and callable(getattr(self._cluster, name))
            and name not in UNPROXIED_CLUSTER_METHODS
        ):
            command = getattr(self._cluster, name)
            wrapped_command = retry_request(command)
            wrapped_command.__name__ = name

            return wrapped_command
        return self.__getattribute__(name)


class ZDOClusterHandler(LogMixin):
    """Cluster handler for ZDO events."""

    def __init__(self, device) -> None:
        """Initialize ZDOClusterHandler."""
        self.name = CLUSTER_HANDLER_ZDO
        self._cluster = device.device.endpoints[0]
        self._zha_device = device
        self._status = ClusterHandlerStatus.CREATED
        self._unique_id = f"{str(device.ieee)}:{device.name}_ZDO"

    def on_add(self) -> None:
        """Call when cluster handler is added."""
        self._cluster.add_listener(self)

    def on_remove(self) -> None:
        """Call when cluster handler will be removed."""
        self._cluster.remove_listener(self)

    @property
    def unique_id(self):
        """Return the unique id for this cluster handler."""
        return self._unique_id

    @property
    def cluster(self):
        """Return the aigpy cluster for this cluster handler."""
        return self._cluster

    @property
    def status(self):
        """Return the status of the cluster handler."""
        return self._status

    def device_announce(self, zigpy_device):
        """Device announce handler."""

    def permit_duration(self, duration):
        """Permit handler."""

    async def async_initialize(self, from_cache):  # pylint: disable=unused-argument
        """Initialize cluster handler."""
        self._status = ClusterHandlerStatus.INITIALIZED

    async def async_configure(self):
        """Configure cluster handler."""
        self._status = ClusterHandlerStatus.CONFIGURED

    def log(self, level, msg, *args, **kwargs):
        """Log a message."""
        msg = f"[%s:ZDO](%s): {msg}"
        args = (self._zha_device.nwk, self._zha_device.model) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class ClientClusterHandler(ClusterHandler):
    """ClusterHandler for Zigbee client (output) clusters."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize ClientClusterHandler."""
        super().__init__(*args, **kwargs)
        self._unique_id += "_CLIENT"
        self._generic_id += "_client"
        self._id += "_client"

    def attribute_updated(self, attrid: int, value: Any, timestamp: datetime) -> None:
        """Handle an attribute updated on this cluster."""
        super().attribute_updated(attrid, value, timestamp)

        try:
            attr_name = self._cluster.attributes[attrid].name
        except KeyError:
            attr_name = "Unknown"

        self.emit_zha_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTRIBUTE_ID: attrid,
                ATTRIBUTE_NAME: attr_name,
                ATTRIBUTE_VALUE: value,
                VALUE: value,
            },
        )

    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""
        if (
            self._cluster.server_commands is not None
            and self._cluster.server_commands.get(command_id) is not None
        ):
            self.emit_zha_event(self._cluster.server_commands[command_id].name, args)
