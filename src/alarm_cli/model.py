"""The ``Alarm`` dataclass, ``AlarmState``, and JSON (de)serialisation.

Pure data: this module never touches the filesystem and never reads the clock.
Times arrive from the caller and are stored exactly as given.

Alarms are frozen. A state change produces a new ``Alarm`` (see
:meth:`Alarm.resolve`) rather than mutating one, so nothing can half-apply a
transition to an object another list is still holding.

Bad input raises ``ValueError``. ``store`` catches it and re-raises with the
path of the file the bad record came from, because the user's next move is to
open that file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

#: Keys of a serialised alarm, in the order they are written.
FIELDS = ("id", "message", "fire_at", "created_at", "state", "resolved_at")


class AlarmState(StrEnum):
    """``armed`` is the only state an alarm can leave."""

    ARMED = "armed"
    FIRED = "fired"
    MISSED = "missed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self is not AlarmState.ARMED


@dataclass(frozen=True, slots=True)
class Alarm:
    """One alarm, as it lives in ``alarms.json``.

    ``fire_at`` is a full local date-time with its UTC offset, not a bare clock
    time: missed detection has to tell yesterday's 07:00 from today's (FR-10).
    """

    id: int
    message: str | None
    fire_at: datetime
    created_at: datetime
    state: AlarmState = AlarmState.ARMED
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("fire_at", "created_at", "resolved_at"):
            value: datetime | None = getattr(self, name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(
                    f"alarm {self.id}: {name} has no UTC offset; "
                    "alarms store an absolute instant, not a wall-clock time"
                )
        if self.state.is_terminal and self.resolved_at is None:
            raise ValueError(
                f"alarm {self.id}: state {self.state.value!r} needs a resolved_at"
            )
        if not self.state.is_terminal and self.resolved_at is not None:
            raise ValueError(
                f"alarm {self.id}: an armed alarm cannot have a resolved_at"
            )

    def resolve(self, state: AlarmState, at: datetime) -> Alarm:
        """Return this alarm moved to a terminal ``state``, stamped ``at``."""
        if not state.is_terminal:
            raise ValueError(f"{state.value!r} is not a terminal state")
        if self.state.is_terminal:
            raise ValueError(
                f"alarm {self.id} is already {self.state.value}; "
                "terminal states are final"
            )
        return replace(self, state=state, resolved_at=at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message": self.message,
            "fire_at": self.fire_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "resolved_at": None if self.resolved_at is None else self.resolved_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Alarm:
        if not isinstance(raw, dict):
            raise ValueError(f"expected an alarm object, found {type(raw).__name__}")
        missing = [key for key in FIELDS if key not in raw]
        if missing:
            raise ValueError(f"alarm is missing {', '.join(missing)}")

        alarm_id = raw["id"]
        # bool is an int in Python, and `"id": true` is not an id.
        if not isinstance(alarm_id, int) or isinstance(alarm_id, bool):
            raise ValueError(f"id must be an integer, found {alarm_id!r}")

        message = raw["message"]
        if message is not None and not isinstance(message, str):
            raise ValueError(f"alarm {alarm_id}: message must be a string or null")

        try:
            state = AlarmState(raw["state"])
        except ValueError:
            known = ", ".join(s.value for s in AlarmState)
            raise ValueError(
                f"alarm {alarm_id}: unknown state {raw['state']!r} (expected one of {known})"
            ) from None

        return cls(
            id=alarm_id,
            message=message,
            fire_at=_parse_time(raw["fire_at"], alarm_id, "fire_at"),
            created_at=_parse_time(raw["created_at"], alarm_id, "created_at"),
            state=state,
            resolved_at=_parse_optional_time(raw["resolved_at"], alarm_id, "resolved_at"),
        )


def _parse_time(value: Any, alarm_id: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"alarm {alarm_id}: {field} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"alarm {alarm_id}: {field} is not an ISO 8601 date-time: {value!r}"
        ) from None


def _parse_optional_time(value: Any, alarm_id: Any, field: str) -> datetime | None:
    if value is None:
        return None
    return _parse_time(value, alarm_id, field)
