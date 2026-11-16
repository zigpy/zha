"""Records of the bindings and attribute reporting applied to a device.

Each binding and each attribute reporting configuration is one record in the device's
store, in namespace `zha.applied_config`, keyed by `binding_key` and `reporting_key`.
Nothing acts on the records yet: they are there for diagnostics and for features built
on them later (re-applying configuration that is out of date, listing a device's
bindings, respecting user-made bindings).

A record keeps separate facets:

- `desired_by`: who wants the item, with its settings. `zha` is ZHA's own
  configuration, the cluster configs of the device's entities; `user` is a binding
  made or removed through the device's bind and unbind methods (`bound: false` keeps
  a user's unbind as a tombstone, so the intent is not lost).
- `last_attempt`: the most recent request and its outcome, either the `status` the
  device answered (ZDO for bindings, ZCL for reporting) or the `error` (exception
  class) when it did not answer, for example a timeout. A request that failed with an
  error may still have been applied.
- `acknowledged`: what the device last accepted, and when. It is kept when a later
  attempt fails, and marked `invalidated` when the device joins again, since a
  rejoining device may have been reset. An acknowledgement means the device accepted the request, not that it
  still holds the setting (a factory reset or another controller can change it, and
  some devices accept reporting configuration and ignore it). A reporting attribute
  missing from the device's response counts as accepted, as the ZCL specifies.
- `quirk_handler`: present when the cluster's quirk replaces the request, so the
  outcome may not come from the device (local clusters answer success themselves).

Stale records: after a configuration run, a ZHA requirement that the run no longer
produced is marked with `stale_since` (the time of the first run without it), and a
later run that wants the item again clears the mark. Records are never deleted: they
are kept so diagnostics show the history, and they go with the device's store when the
device is removed. A run that is skipped (`skip_configuration`) does not mark anything,
and a user's requirement is never marked stale by a configuration run.

Bindings are identified by source endpoint, cluster and destination, as the device's
binding table does; whether ZHA bound the cluster as a server or a client is kept as
`sides` in ZHA's requirement. Reporting is identified by endpoint, cluster side,
cluster, attribute and effective manufacturer code.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
import enum
import logging
from typing import TYPE_CHECKING, Any, Final, Literal

import zigpy.zcl
from zigpy.zdo import types as zdo_types

from zha.zigbee.store import get_store_namespace, store_key

if TYPE_CHECKING:
    from zigpy.device import BaseDevice as ZigpyBaseDevice
    from zigpy.store import StoreNamespace
    from zigpy.types import EUI64
    from zigpy.zcl import ReportingConfig
    from zigpy.zcl.foundation import ZCLAttributeDef

_LOGGER = logging.getLogger(__name__)

APPLIED_CONFIG_NAMESPACE: Final = "zha.applied_config"

# Version of the record layout, stored with each row. A row written by a newer version
# is left alone.
APPLIED_CONFIG_VERSION: Final = 1

# `MultiAddress.addrmode` of a group and of an IEEE address with an endpoint
ADDR_MODE_GROUP: Final = 0x01
ADDR_MODE_IEEE: Final = 0x03

type Origin = Literal["zha", "user"]
type BindOperation = Literal["bind", "unbind"]


@dataclass(frozen=True, kw_only=True)
class ConfigResult:
    """Outcome of one configuration request for one item.

    `status` is the name of the status the device answered. `error` is the class name
    of the exception raised instead, when there was no answer to read a status from.
    """

    status: str | None = None
    error: str | None = None

    @classmethod
    def from_status(cls, status: Any) -> ConfigResult:
        """Return the result for a status answered by the device."""
        return cls(status=status_name(status))

    @classmethod
    def from_exception(cls, exc: BaseException) -> ConfigResult:
        """Return the result for a request that raised instead of answering."""
        return cls(error=type(exc).__name__)

    def is_acknowledged(self, operation: BindOperation | None = None) -> bool:
        """Return whether the device accepted the request.

        An unbind answered with `NO_ENTRY` is done: the binding is not there.
        """
        if self.status == "SUCCESS":
            return True

        return operation == "unbind" and self.status == "NO_ENTRY"

    def as_json(self) -> dict[str, Any]:
        """Return the result as stored, leaving out what is not set."""
        result: dict[str, Any] = {}

        if self.status is not None:
            result["status"] = self.status

        if self.error is not None:
            result["error"] = self.error

        return result


def status_name(status: Any) -> str:
    """Return the name of a ZDO or ZCL status.

    ZDO requests answer with a ZDO status, which may arrive as a plain integer; quirk
    clusters answer binds with a ZCL status.
    """
    if isinstance(status, enum.Enum):
        return status.name

    for member in zdo_types.Status:
        if member.value == status:
            return member.name

    return f"undefined_0x{int(status):02x}"


def destination_key_parts(destination: zdo_types.MultiAddress) -> tuple[str | int, ...]:
    """Return the key parts of a binding's destination."""
    if destination.addrmode == ADDR_MODE_GROUP:
        return ("group", destination.nwk)

    if destination.addrmode == ADDR_MODE_IEEE:
        return ("ieee", str(destination.ieee), destination.endpoint)

    raise ValueError(f"Not a binding destination: {destination!r}")


def binding_key(
    endpoint_id: int, cluster_id: int, destination: zdo_types.MultiAddress
) -> str:
    """Return the record key of a binding."""
    return store_key(
        "binding", endpoint_id, cluster_id, *destination_key_parts(destination)
    )


def reporting_key(
    endpoint_id: int,
    is_server: bool,
    cluster_id: int,
    attribute_id: int,
    manufacturer_code: int | None,
) -> str:
    """Return the record key of an attribute's reporting configuration."""
    return store_key(
        "reporting",
        endpoint_id,
        "server" if is_server else "client",
        cluster_id,
        attribute_id,
        manufacturer_code,
    )


def destination_json(
    destination: zdo_types.MultiAddress, coordinator_ieee: EUI64
) -> dict[str, Any]:
    """Return a binding's destination as stored.

    `coordinator` marks the logical intent beside the concrete address it resolved to.
    """
    if destination.addrmode == ADDR_MODE_GROUP:
        return {"group": destination.nwk}

    result: dict[str, Any] = {
        "ieee": str(destination.ieee),
        "endpoint": destination.endpoint,
    }

    if destination.ieee == coordinator_ieee:
        result["coordinator"] = True

    return result


def quirk_replaces(cluster: zigpy.zcl.Cluster, *methods: str) -> bool:
    """Return whether code outside zigpy implements any of the cluster's `methods`.

    Quirk clusters that replace `bind` or reporting configuration may answer without
    sending anything (zhaquirks' `LocalDataCluster` reports success itself).
    """
    for method in methods:
        for cls in type(cluster).__mro__:
            if method in vars(cls):
                if not cls.__module__.startswith("zigpy."):
                    return True

                break

    return False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AppliedConfigRecorder:
    """Writes the records of one device. Does nothing if the device has no store.

    One recorder is used per configuration run, so that `mark_stale` knows which of
    ZHA's requirements the run produced.
    """

    def __init__(self, zigpy_device: ZigpyBaseDevice) -> None:
        """Initialize the recorder for a zigpy device."""
        self._device = zigpy_device
        self._namespace: StoreNamespace | None = get_store_namespace(
            zigpy_device, APPLIED_CONFIG_NAMESPACE
        )
        # Keys of ZHA's requirements produced by this run
        self._zha_keys: set[str] = set()
        # Whether an item of this run could not be keyed, so `mark_stale` cannot tell
        # its earlier record from one that is no longer wanted
        self._incomplete = False

    @property
    def enabled(self) -> bool:
        """Return whether records are written."""
        return self._namespace is not None

    def note_incomplete(self) -> None:
        """Note that an item of this run could not be keyed; nothing is marked stale."""
        self._incomplete = True

    def _load(self, key: str) -> dict[str, Any] | None:
        """Return a copy of a record to update, or `None` to leave it alone."""
        assert self._namespace is not None

        if key not in self._namespace:
            return {}

        item = self._namespace.item(key)

        if item.version > APPLIED_CONFIG_VERSION:
            # Written by a newer version, which owns its layout
            return None

        if not isinstance(item.value, dict):
            return {}

        return copy.deepcopy(item.value)

    def _save(self, key: str, record: dict[str, Any]) -> None:
        assert self._namespace is not None
        self._namespace.set(key, record, version=APPLIED_CONFIG_VERSION)

    def record_binding(
        self,
        *,
        endpoint_id: int,
        cluster_id: int,
        destination: zdo_types.MultiAddress,
        operation: BindOperation,
        origin: Origin,
        result: ConfigResult,
        side: Literal["server", "client"] | None = None,
        quirk_handler: bool = False,
    ) -> None:
        """Record a bind or unbind request and its outcome.

        ZHA's configuration only binds, and passes the cluster's `side`.
        """
        if self._namespace is None:
            return

        try:
            key = binding_key(endpoint_id, cluster_id, destination)
        except Exception:
            self.note_incomplete()
            raise

        first_in_run = key not in self._zha_keys

        if origin == "zha":
            # Registered first, so a failed write never makes the item look unwanted
            self._zha_keys.add(key)

        record = self._load(key)

        if record is None:
            return

        now = _now()
        record["kind"] = "binding"
        record["endpoint"] = endpoint_id
        record["cluster_id"] = cluster_id
        record["destination"] = destination_json(
            destination, self._device.application.state.node_info.ieee
        )
        desired_by = record.setdefault("desired_by", {})

        if origin == "zha":
            # Both sides of a cluster ID on an endpoint make the same binding
            sides = set(desired_by.get("zha", {}).get("sides", ()))

            if first_in_run:
                sides.clear()

            if side is not None:
                sides.add(side)

            desired_by["zha"] = {"sides": sorted(sides)}
        else:
            desired_by["user"] = {"bound": operation == "bind", "time": now}

        record["last_attempt"] = {
            "time": now,
            "operation": operation,
            "origin": origin,
            **result.as_json(),
        }

        if result.is_acknowledged(operation):
            record["acknowledged"] = {"bound": operation == "bind", "time": now}

        if quirk_handler:
            record["quirk_handler"] = True
        else:
            record.pop("quirk_handler", None)

        self._save(key, record)

    def record_reporting(
        self,
        *,
        cluster: zigpy.zcl.Cluster,
        attr_def: ZCLAttributeDef,
        manufacturer_code: int | None,
        desired: ReportingConfig,
        result: ConfigResult,
        quirk_handler: bool = False,
    ) -> None:
        """Record a reporting configuration request of ZHA's and its outcome."""
        if self._namespace is None:
            return

        try:
            key = reporting_key(
                cluster.endpoint.endpoint_id,
                cluster.is_server,
                cluster.cluster_id,
                attr_def.id,
                manufacturer_code,
            )
        except Exception:
            self.note_incomplete()
            raise

        # Registered first, so a failed write never makes the item look unwanted
        self._zha_keys.add(key)
        record = self._load(key)

        if record is None:
            return

        now = _now()
        settings = {
            "min": desired.min_interval,
            "max": desired.max_interval,
            "change": desired.reportable_change,
        }
        record["kind"] = "reporting"
        record["endpoint"] = cluster.endpoint.endpoint_id
        record["side"] = "server" if cluster.is_server else "client"
        record["cluster_id"] = cluster.cluster_id
        record["attribute_id"] = attr_def.id
        record["attribute"] = attr_def.name
        record["manufacturer_code"] = manufacturer_code
        record.setdefault("desired_by", {})["zha"] = settings
        record["last_attempt"] = {"time": now, **result.as_json()}

        if result.is_acknowledged():
            record["acknowledged"] = {**settings, "time": now}

        if quirk_handler:
            record["quirk_handler"] = True
        else:
            record.pop("quirk_handler", None)

        self._save(key, record)

    def mark_stale(self) -> None:
        """Mark ZHA's requirements that this run did not produce as stale.

        Call it only after a complete configuration run. Does nothing if an item of
        the run could not be keyed (`note_incomplete`).
        """
        if self._namespace is None:
            return

        if self._incomplete:
            _LOGGER.debug(
                "[%s] Not marking stale records: this run's records are incomplete",
                self._device.ieee,
            )
            return

        now = _now()

        for key in list(self._namespace):
            if key in self._zha_keys:
                continue

            record = self._load(key)

            if not record or "zha" not in record.get("desired_by", {}):
                continue

            requirement = record["desired_by"]["zha"]

            if "stale_since" in requirement:
                continue

            requirement["stale_since"] = now
            self._save(key, record)

    def mark_joined(self) -> None:
        """Mark every acknowledgement as from before the device joined again.

        A device that joins (again) may have been reset, which clears its bindings and
        reporting configuration. The acknowledgement is kept for history, with
        `invalidated` saying why it may no longer hold; the next accepted request
        replaces it.
        """
        if self._namespace is None:
            return

        now = _now()

        for key in list(self._namespace):
            record = self._load(key)

            if not record or not isinstance(record.get("acknowledged"), dict):
                continue

            if "invalidated" in record["acknowledged"]:
                continue

            record["acknowledged"]["invalidated"] = {"reason": "joined", "time": now}
            self._save(key, record)
