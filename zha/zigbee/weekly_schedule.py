"""Heat-only thermostat weekly schedules.

`WeeklyScheduleProvider` implements validation, caching, snapshots, change
detection and verified per-day writes. A thermostat family only implements the
transport primitives. `ZclWeeklySchedule` uses the standard ZCL Thermostat
cluster commands. Quirks opt in by exposing a feature registered in
`WEEKLY_SCHEDULE_PROVIDERS`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Mapping, Sequence
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

import zigpy.exceptions
import zigpy.types as t
from zigpy.zcl import Cluster, foundation
from zigpy.zcl.clusters.hvac import SeqDayOfWeek, SeqMode, Thermostat

from zha.event import EventBase
from zha.exceptions import ZHAException
from zha.quirks import THERMOSTAT_WEEKLY_SCHEDULE

if TYPE_CHECKING:
    from zha.zigbee.device import ZigbeeDevice

WEEKDAYS = {
    "monday": SeqDayOfWeek.Monday,
    "tuesday": SeqDayOfWeek.Tuesday,
    "wednesday": SeqDayOfWeek.Wednesday,
    "thursday": SeqDayOfWeek.Thursday,
    "friday": SeqDayOfWeek.Friday,
    "saturday": SeqDayOfWeek.Saturday,
    "sunday": SeqDayOfWeek.Sunday,
}

type ScheduleInput = Mapping[str, Sequence[tuple[int, int]]]

_TRANSPORT_ERRORS = (
    zigpy.exceptions.ZigbeeException,
    TimeoutError,
    KeyError,
    TypeError,
    ValueError,
)


class ScheduleTransition(TypedDict):
    """A schedule transition in local time and degrees Celsius."""

    time: str
    temperature: float


class ScheduleDay(TypedDict):
    """A known or unknown day's cached transitions."""

    transitions: list[ScheduleTransition] | None
    updated_at: str | None


class ScheduleSnapshot(TypedDict):
    """A snapshot of the seven weekdays."""

    days: dict[str, ScheduleDay]
    complete: bool


class ScheduleResult(ScheduleSnapshot):
    """The current cache, the pre-write snapshot and the days written last."""

    pre_write_snapshot: ScheduleSnapshot | None
    written_days: list[str]


@dataclass(frozen=True, kw_only=True)
class WeeklyScheduleCapabilities:
    """Limits a provider enforces before communicating with a thermostat.

    `max_transitions_per_day` is `None` when no verified device limit is known.
    `temperature_step` is in centi-degrees Celsius.
    """

    max_transitions_per_day: int | None = None
    temperature_step: int = 1
    supports_clear: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "max_transitions_per_day": self.max_transitions_per_day,
            "temperature_step": self.temperature_step / 100,
            "supports_clear": self.supports_clear,
        }


class Transition(NamedTuple):
    """A transition in minutes after local midnight and centi-degrees Celsius."""

    minute: int
    centi_celsius: int


class WriteAcknowledgement(NamedTuple):
    """The outcome of a day write before it is verified by reading it back.

    `error` describes a missing or unexpected acknowledgement, which a matching
    read-back can still recover. `rejected` marks an explicit device failure.
    """

    error: Exception | None = None
    rejected: bool = False


@dataclass(frozen=True)
class _CachedDay:
    transitions: tuple[Transition, ...]
    updated_at: datetime


class WeeklyScheduleProvider(EventBase, ABC):
    """Serialize, cache and verify schedule operations for one device endpoint."""

    EVENT_VERIFIED_CHANGED = "weekly_schedule_verified_changed"
    capabilities = WeeklyScheduleCapabilities()

    def __init__(self, device: ZigbeeDevice, endpoint_id: int) -> None:
        """Create an endpoint schedule provider."""
        super().__init__()
        self._device = device
        self._endpoint_id = endpoint_id
        self.lock = asyncio.Lock()
        self._days: dict[str, _CachedDay] = {}
        self._pre_write_snapshot: ScheduleSnapshot | None = None
        self._written_days: list[str] = []
        self._verified_schedule: dict[str, tuple[Transition, ...]] | None = None

    # Device-family primitives.

    def _begin(self) -> None:  # noqa: B027
        """Prepare an operation; raise if the device cannot be addressed."""

    def _ensure_target(self) -> None:  # noqa: B027
        """Raise if the addressed device changed during an operation."""

    @abstractmethod
    async def _async_read_day(self, day: str) -> tuple[Transition, ...]:
        """Read one heat day from the device."""

    @abstractmethod
    async def _async_heat_limits(self) -> tuple[int, int]:
        """Read fresh heat setpoint limits in centi-degrees Celsius."""

    @abstractmethod
    def _check_write_support(self) -> None:
        """Raise if the device cannot write schedules."""

    def _check_encodable(  # noqa: B027
        self, day: str, transitions: tuple[Transition, ...]
    ) -> None:
        """Raise if a day cannot be encoded for the device."""

    @abstractmethod
    async def _async_write_day(
        self, day: str, transitions: tuple[Transition, ...]
    ) -> WriteAcknowledgement:
        """Write one heat day; transport failures are returned, not raised."""

    def _check_clear_support(self) -> None:
        """Raise if the device cannot clear its schedule."""
        if not self.capabilities.supports_clear:
            raise ZHAException("The thermostat does not support schedule clearing")

    async def _async_clear_all(self) -> None:
        """Clear the device schedule, raising if it is not confirmed."""
        raise ZHAException("The thermostat does not support schedule clearing")

    # Shared behaviour.

    @property
    def has_verified_schedule(self) -> bool:
        """Return whether a complete uploaded schedule is still verified."""
        return self._verified_schedule is not None

    def _set_verified_schedule(
        self, schedule: dict[str, tuple[Transition, ...]] | None
    ) -> None:
        was_verified = self.has_verified_schedule
        self._verified_schedule = schedule
        if self.has_verified_schedule != was_verified:
            self.emit(self.EVENT_VERIFIED_CHANGED, self.has_verified_schedule)

    def invalidate(self, day_bitmap: int | None = None) -> None:
        """Mark selected days unknown without discarding the pre-write snapshot."""
        self._set_verified_schedule(None)
        for day, bit in WEEKDAYS.items():
            if day_bitmap is None or day_bitmap & bit:
                self._days.pop(day, None)

    def _reset(self) -> None:
        self.invalidate()
        self._pre_write_snapshot = None
        self._written_days = []

    def _validate_schedule(
        self, schedule: ScheduleInput
    ) -> dict[str, tuple[Transition, ...]]:
        """Validate all days before communicating with a thermostat."""
        if set(schedule) != set(WEEKDAYS):
            raise ZHAException(
                "A weekly schedule must contain exactly the seven weekdays"
            )

        maximum_count = self.capabilities.max_transitions_per_day or 255
        step = self.capabilities.temperature_step
        result: dict[str, tuple[Transition, ...]] = {}
        for day in WEEKDAYS:
            entries = schedule[day]
            if not entries or len(entries) > maximum_count:
                raise ZHAException(
                    f"{day} must contain between 1 and {maximum_count} transitions"
                )
            transitions = []
            previous_minute = -1
            for entry in entries:
                if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                    raise ZHAException(f"Invalid transition for {day}: {entry!r}")
                minute, temperature = entry
                if (
                    isinstance(minute, bool)
                    or not isinstance(minute, int)
                    or not 0 <= minute < 1440
                    or minute <= previous_minute
                ):
                    raise ZHAException(
                        f"Invalid or duplicate transition time for {day}"
                    )
                if (
                    isinstance(temperature, bool)
                    or not isinstance(temperature, int)
                    or not -32767 <= temperature <= 32767
                ):
                    raise ZHAException(f"Invalid heat setpoint for {day}")
                if temperature % step:
                    raise ZHAException(
                        f"{day} setpoints must be multiples of {step / 100} °C"
                    )
                transitions.append(Transition(minute, temperature))
                previous_minute = minute
            if transitions[0].minute != 0:
                raise ZHAException(f"{day} must begin at 00:00")
            result[day] = tuple(transitions)
        return result

    def _snapshot(self) -> ScheduleSnapshot:
        days: dict[str, ScheduleDay] = {}
        for day in WEEKDAYS:
            cached = self._days.get(day)
            days[day] = {
                "transitions": (
                    [
                        {
                            "time": f"{item.minute // 60:02}:{item.minute % 60:02}",
                            "temperature": item.centi_celsius / 100,
                        }
                        for item in cached.transitions
                    ]
                    if cached is not None
                    else None
                ),
                "updated_at": cached.updated_at.isoformat() if cached else None,
            }
        return {"days": days, "complete": len(self._days) == len(WEEKDAYS)}

    def _result(self) -> ScheduleResult:
        return {
            **self._snapshot(),
            "pre_write_snapshot": copy.deepcopy(self._pre_write_snapshot),
            "written_days": list(self._written_days),
        }

    async def _read_day(self, day: str) -> tuple[Transition, ...]:
        transitions = tuple(await self._async_read_day(day))
        previous_minute = -1
        for minute, temperature in transitions:
            if (
                not isinstance(minute, int)
                or not 0 <= minute < 1440
                or minute <= previous_minute
                or not isinstance(temperature, int)
                or not -32767 <= temperature <= 32767
            ):
                raise ZHAException(f"Invalid schedule transition returned for {day}")
            previous_minute = minute
        self._days[day] = _CachedDay(transitions, datetime.now(UTC))
        return transitions

    async def _refresh(self, *, preserve_verification: bool = False) -> None:
        verified = self._verified_schedule if preserve_verification else None
        if preserve_verification:
            self._days.clear()
        else:
            self.invalidate()
        try:
            for day in WEEKDAYS:
                await self._read_day(day)
        finally:
            if verified is not None and (
                len(self._days) != len(WEEKDAYS)
                or any(self._days[day].transitions != verified[day] for day in WEEKDAYS)
            ):
                self._set_verified_schedule(None)

    async def async_get(self, *, refresh: bool = True) -> ScheduleResult:
        """Return a fresh schedule or the explicitly requested in-memory cache."""
        async with self.lock:
            self._begin()
            if refresh:
                await self._refresh(preserve_verification=True)
            return self._result()

    def _partial_failure(
        self,
        day: str,
        attempted: list[str],
        before: dict[str, tuple[Transition, ...]],
        reason: str,
    ) -> ZHAException:
        changed = [
            name
            for name in attempted
            if name in self._days and self._days[name].transitions != before[name]
        ]
        unknown = [name for name in attempted if name not in self._days]
        remaining = [name for name in WEEKDAYS if name not in attempted]
        return ZHAException(
            f"Schedule upload stopped on {day}: {reason}. "
            f"Observed changed days: {changed}; unknown attempted days: {unknown}; "
            f"unattempted days: {remaining}. No rollback was attempted."
        )

    async def async_set(
        self, schedule: ScheduleInput, *, only_changed: bool = False
    ) -> ScheduleResult:
        """Upload and verify a complete heat schedule without changing mode or clock.

        With `only_changed`, days whose fresh read already matches are skipped.
        """
        validated = self._validate_schedule(schedule)
        async with self.lock:
            self._begin()
            self._pre_write_snapshot = None
            self._written_days = []
            minimum, maximum = await self._async_heat_limits()
            self._check_write_support()

            for day, transitions in validated.items():
                for item in transitions:
                    if not minimum <= item.centi_celsius <= maximum:
                        raise ZHAException(
                            f"The temperature {item.centi_celsius / 100:g} °C "
                            f"on {day.capitalize()} at "
                            f"{item.minute // 60:02}:{item.minute % 60:02} is "
                            f"{'too low' if item.centi_celsius < minimum else 'too high'}. "
                            "Choose a temperature within the thermostat's "
                            f"allowed range of {minimum / 100:g} to {maximum / 100:g} °C."
                        )
                self._check_encodable(day, transitions)

            await self._refresh()
            before = {day: self._days[day].transitions for day in WEEKDAYS}
            self._pre_write_snapshot = self._snapshot()
            pending = {
                day: transitions
                for day, transitions in validated.items()
                if not only_changed or before[day] != transitions
            }
            attempted: list[str] = []
            for day, transitions in pending.items():
                try:
                    self._ensure_target()
                except ZHAException as exc:
                    raise self._partial_failure(
                        day, attempted, before, str(exc)
                    ) from exc
                attempted.append(day)
                self._written_days.append(day)
                self.invalidate(WEEKDAYS[day])
                acknowledgement = await self._async_write_day(day, transitions)

                try:
                    actual = await self._read_day(day)
                except ZHAException as exc:
                    reason = f"read-back failed: {exc}"
                    if acknowledgement.error is not None:
                        reason = f"{acknowledgement.error}; {reason}"
                    raise self._partial_failure(day, attempted, before, reason) from exc
                if acknowledgement.rejected or actual != transitions:
                    reason = "; ".join(
                        part
                        for part in (
                            str(acknowledgement.error) if acknowledgement.error else "",
                            (
                                "read-back does not match the requested transitions"
                                if actual != transitions
                                else ""
                            ),
                        )
                        if part
                    )
                    raise self._partial_failure(day, attempted, before, reason) from (
                        acknowledgement.error
                    )
            self._set_verified_schedule(validated)
            return self._result()

    async def async_clear(self) -> ScheduleResult:
        """Clear the entire schedule, snapshotting and verifying heat days."""
        async with self.lock:
            self._begin()
            self._pre_write_snapshot = None
            self._written_days = []
            self._check_clear_support()

            await self._refresh()
            self._pre_write_snapshot = self._snapshot()
            self._ensure_target()
            self.invalidate()
            self._written_days = list(WEEKDAYS)
            await self._async_clear_all()

            try:
                await self._refresh()
            except ZHAException as exc:
                raise ZHAException(
                    "Schedule clear was acknowledged, but heat schedule read-back "
                    "failed. The device schedule may have changed. "
                    "No rollback was attempted."
                ) from exc
            remaining = [day for day in WEEKDAYS if self._days[day].transitions]
            if remaining:
                raise ZHAException(
                    f"Schedule clear did not remove heat transitions on {remaining}. "
                    "No rollback was attempted."
                )
            return self._result()


class ZclWeeklySchedule(WeeklyScheduleProvider):
    """Weekly schedules using standard ZCL Thermostat cluster commands."""

    def __init__(self, device: ZigbeeDevice, endpoint_id: int) -> None:
        """Create a ZCL schedule provider."""
        super().__init__(device, endpoint_id)
        self._cluster: Cluster | None = None

    def bind_cluster(self, cluster: Cluster) -> None:
        """Reset cached values when the endpoint's cluster changes."""
        if cluster is not self._cluster:
            self._cluster = cluster
            self._reset()

    def _current_cluster(self) -> Cluster:
        try:
            cluster = self._device.async_get_cluster(
                self._endpoint_id, Thermostat.cluster_id
            )
        except KeyError as exc:
            self._cluster = None
            self._reset()
            raise ZHAException("The thermostat cluster is no longer available") from exc
        self.bind_cluster(cluster)
        return cluster

    @property
    def _bound_cluster(self) -> Cluster:
        assert self._cluster is not None
        return self._cluster

    def _begin(self) -> None:
        self._current_cluster()

    def _ensure_target(self) -> None:
        self._ensure_same_cluster(self._bound_cluster)

    def _ensure_same_cluster(self, cluster: Cluster) -> None:
        if self._current_cluster() is not cluster:
            raise ZHAException("The thermostat cluster changed during the operation")

    async def _async_read_day(self, day: str) -> tuple[Transition, ...]:
        cluster = self._bound_cluster
        try:
            response = await cluster.command(
                Thermostat.ServerCommandDefs.get_weekly_schedule.id,
                days_to_return=WEEKDAYS[day],
                mode_to_return=SeqMode.Heat,
                retries=0,
            )
        except _TRANSPORT_ERRORS as exc:
            raise ZHAException(f"Unable to read the {day} schedule: {exc}") from exc
        self._ensure_same_cluster(cluster)
        if isinstance(response, Exception):
            raise ZHAException(f"Unable to read the {day} schedule") from response
        if isinstance(response, foundation.DefaultResponse):
            raise ZHAException(
                f"Unable to read the {day} schedule: device returned {response.status}"
            )
        if not isinstance(response, t.Struct):
            raise ZHAException(f"Unexpected schedule response for {day}: {response!r}")

        fields = response.as_dict()
        count = fields.get("num_transitions_for_sequence")
        response_days = fields.get("day_of_week_for_sequence")
        mode = fields.get("mode_for_sequence")
        values = fields.get("values")
        if (
            not isinstance(count, int)
            or not 0 <= count <= 255
            or response_days != WEEKDAYS[day]
            or mode != SeqMode.Heat
            or not isinstance(values, (list, tuple))
            or len(values) != count * 2
        ):
            raise ZHAException(f"Malformed or unsupported schedule response for {day}")
        return tuple(
            Transition(*values[index : index + 2]) for index in range(0, len(values), 2)
        )

    async def _async_heat_limits(self) -> tuple[int, int]:
        cluster = self._bound_cluster
        names = ("min_heat_setpoint_limit", "max_heat_setpoint_limit")
        try:
            values, failures = await cluster.read_attributes(
                list(names), allow_cache=False, retries=0
            )
        except _TRANSPORT_ERRORS as exc:
            raise ZHAException(
                f"Unable to read the thermostat heat limits: {exc}"
            ) from exc
        self._ensure_same_cluster(cluster)
        minimum, maximum = (values.get(name) for name in names)
        if (
            failures
            or not isinstance(minimum, int)
            or not isinstance(maximum, int)
            or not -32767 <= minimum <= maximum <= 32767
        ):
            raise ZHAException(
                "Fresh thermostat heat limits are unavailable or invalid"
            )
        return minimum, maximum

    def _check_write_support(self) -> None:
        if (
            Thermostat.ServerCommandDefs.set_weekly_schedule.id
            not in self._bound_cluster.server_commands
        ):
            raise ZHAException("The thermostat does not support schedule writes")

    @staticmethod
    def _payload(day: str, transitions: tuple[Transition, ...]) -> dict[str, Any]:
        return {
            "num_transitions_for_sequence": len(transitions),
            "day_of_week_for_sequence": WEEKDAYS[day],
            "mode_for_sequence": SeqMode.Heat,
            "values": [
                value
                for item in transitions
                for value in (item.minute, item.centi_celsius)
            ],
        }

    def _check_encodable(self, day: str, transitions: tuple[Transition, ...]) -> None:
        command = self._bound_cluster.server_commands[
            Thermostat.ServerCommandDefs.set_weekly_schedule.id
        ]
        try:
            command.schema(**self._payload(day, transitions)).serialize()
        except (ValueError, TypeError, OverflowError) as exc:
            raise ZHAException(f"The {day} schedule cannot be encoded: {exc}") from exc

    async def _async_write_day(
        self, day: str, transitions: tuple[Transition, ...]
    ) -> WriteAcknowledgement:
        command_id = Thermostat.ServerCommandDefs.set_weekly_schedule.id
        try:
            response = await self._bound_cluster.command(
                command_id, **self._payload(day, transitions), retries=0
            )
        except _TRANSPORT_ERRORS as exc:
            return WriteAcknowledgement(exc)
        if isinstance(response, Exception):
            return WriteAcknowledgement(response)
        if (
            not isinstance(response, foundation.DefaultResponse)
            or response.command_id != command_id
        ):
            return WriteAcknowledgement(
                ZHAException(f"Unexpected schedule write acknowledgement: {response!r}")
            )
        if response.status != foundation.Status.SUCCESS:
            return WriteAcknowledgement(
                ZHAException(f"Schedule write returned status {response.status}"),
                rejected=True,
            )
        return WriteAcknowledgement()

    def _check_clear_support(self) -> None:
        if (
            Thermostat.ServerCommandDefs.clear_weekly_schedule.id
            not in self._bound_cluster.server_commands
        ):
            raise ZHAException("The thermostat does not support schedule clearing")

    async def _async_clear_all(self) -> None:
        command_id = Thermostat.ServerCommandDefs.clear_weekly_schedule.id
        unconfirmed = (
            "Unable to confirm schedule clearing; the device schedule "
            "may have changed. No rollback was attempted."
        )
        try:
            response = await self._bound_cluster.command(command_id, retries=0)
        except _TRANSPORT_ERRORS as exc:
            raise ZHAException(unconfirmed) from exc
        if isinstance(response, Exception):
            raise ZHAException(unconfirmed) from response
        if (
            not isinstance(response, foundation.DefaultResponse)
            or response.command_id != command_id
        ):
            raise ZHAException(
                f"Unexpected schedule clear acknowledgement: {response!r}. "
                "The device schedule may have changed. No rollback was attempted."
            )
        if response.status != foundation.Status.SUCCESS:
            raise ZHAException(
                f"Schedule clear returned status {response.status}. "
                "The device schedule may have changed. No rollback was attempted."
            )


# Exposed quirk feature -> provider. Other thermostat families register their
# own feature and provider here.
WEEKLY_SCHEDULE_PROVIDERS: dict[str, type[WeeklyScheduleProvider]] = {
    THERMOSTAT_WEEKLY_SCHEDULE: ZclWeeklySchedule,
}
