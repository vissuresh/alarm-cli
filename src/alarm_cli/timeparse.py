"""``"HH:MM"`` plus a ``now`` to the next occurrence as an aware datetime.

``now`` is always a parameter: this module never reads the clock itself. That
is the seam the test suite rests on.

The result is the *next* occurrence — today if that clock time is still ahead,
tomorrow otherwise — carrying the timezone of the ``now`` it was resolved
against, because an alarm stores an absolute instant rather than a wall-clock
time (FR-10).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

#: What the user is allowed to type, named in every rejection message.
ACCEPTED_FORMAT = "HH:MM in 24-hour form, e.g. 07:00 or 14:30"

# Zero-padded and exactly two digits each: "7:00" and "0700" are rejected rather
# than guessed at, because guessing at a time an alarm will fire at is worse
# than making the user type two more characters. `[0-9]` rather than `\d`,
# which also matches the full-width digits a copy-paste can carry in.
_HHMM = re.compile(r"^([0-9]{2}):([0-9]{2})$")


class TimeFormatError(ValueError):
    """The user typed a time that cannot be read.

    Its message names the accepted format. The client prints it and exits 1
    (FR-2); nothing is written to the store.
    """


def next_occurrence(hhmm: str, now: datetime) -> datetime:
    """Resolve ``hhmm`` to the next instant it names, relative to ``now``.

    Today at ``hhmm`` if that is strictly after ``now``; tomorrow otherwise —
    so asking for the time it already is sets an alarm for tomorrow, not one
    that has already passed.

    Raises :class:`TimeFormatError` for anything the user could have typed
    wrong. A naive ``now`` is a caller bug, not user input, and raises
    ``ValueError``.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("next_occurrence needs an aware `now`; pass datetime.now().astimezone()")

    hour, minute = _split(hhmm)
    today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if today > now:
        return today
    return today + timedelta(days=1)


def _split(hhmm: str) -> tuple[int, int]:
    match = _HHMM.match(hhmm.strip()) if isinstance(hhmm, str) else None
    if match is None:
        raise TimeFormatError(f"{hhmm!r} is not a time; expected {ACCEPTED_FORMAT}")

    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23:
        raise TimeFormatError(f"{hhmm!r} has no hour {hour}; expected {ACCEPTED_FORMAT}")
    if minute > 59:
        raise TimeFormatError(f"{hhmm!r} has no minute {minute}; expected {ACCEPTED_FORMAT}")
    return hour, minute
