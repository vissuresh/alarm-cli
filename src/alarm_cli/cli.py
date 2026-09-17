"""The argparse surface: parse, delegate, format, set the exit code.

Nothing imports this module, and this is the only module that formats output
for a human. Everything below it returns data.

`now` and the store root are parameters of :func:`main`, defaulted from the
clock and the environment exactly once, at the entry point. Tests drive the
commands through `main` with both pinned (NFR-6).

Exit codes: 0 success, 1 a handled error, 2 an argparse usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from alarm_cli import __version__, store
from alarm_cli.model import Alarm, AlarmState
from alarm_cli.store import StoreError
from alarm_cli.timeparse import ACCEPTED_FORMAT, TimeFormatError, next_occurrence

#: Absolute times are shown to the minute, because that is the only precision
#: an alarm has (limitation 8).
TIME_FORMAT = "%Y-%m-%d %H:%M"

#: Stands in for an alarm with no message, so a column is never blank.
NO_MESSAGE = "-"


# --- commands --------------------------------------------------------------


def cmd_add(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-1: resolve the time, store an armed alarm, print what was set."""
    # Parsed before the store is opened, so a bad time cannot leave a
    # half-written store behind (FR-2).
    fire_at = next_occurrence(args.time, now)

    with store.transaction(root) as alarms:
        alarm = alarms.add(
            fire_at=fire_at,
            created_at=now,
            message=_clean(args.message),
        )

    print(
        f"alarm {alarm.id} set for {fire_at.strftime(TIME_FORMAT)} "
        f"(in {format_delta(fire_at - now)})"
    )
    _warn_if_no_daemon(root)
    return 0


def cmd_list(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-3, FR-4: armed alarms by fire time; with --all, the history too."""
    alarms = store.load(root)

    armed = sorted(alarms.armed(), key=lambda alarm: (alarm.fire_at, alarm.id))
    if armed:
        print(_armed_table(armed, now))
    else:
        print("no armed alarms")

    if args.all:
        # `resolved_at` is never None in a terminal state; the model guarantees it.
        history = sorted(
            (alarm for alarm in alarms.alarms if alarm.state.is_terminal),
            key=lambda alarm: (alarm.resolved_at, alarm.id),
        )
        print()
        print(_history_table(history) if history else "no past alarms")

    return 0


def cmd_cancel(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-5: armed -> cancelled. Anything else exits 1 and changes nothing."""
    with store.transaction(root) as alarms:
        alarm = alarms.get(args.id)
        if alarm is None:
            return _fail(f"no alarm with id {args.id}")
        if alarm.state is not AlarmState.ARMED:
            return _fail(
                f"alarm {alarm.id} is already {alarm.state.value}; "
                "only an armed alarm can be cancelled"
            )
        alarms.update(alarm.resolve(AlarmState.CANCELLED, now))

    print(f"alarm {alarm.id} cancelled")
    _warn_if_no_daemon(root)
    return 0


# --- formatting ------------------------------------------------------------


def format_delta(delta: timedelta) -> str:
    """A rough, readable "8h 12m". Truncated, never rounded up.

    Coarse on purpose: the columns it fills are read at a glance, and a wrong
    minute matters less than a number that is hard to scan.
    """
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        # An armed alarm in the past means nothing was running to ring it.
        return "due"

    minutes, _ = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def _armed_table(alarms: Sequence[Alarm], now: datetime) -> str:
    return _table(
        ("ID", "FIRES AT", "IN", "MESSAGE"),
        [
            (
                str(alarm.id),
                alarm.fire_at.strftime(TIME_FORMAT),
                format_delta(alarm.fire_at - now),
                alarm.message or NO_MESSAGE,
            )
            for alarm in alarms
        ],
    )


def _history_table(alarms: Sequence[Alarm]) -> str:
    return _table(
        ("ID", "FIRES AT", "STATE", "RESOLVED AT", "MESSAGE"),
        [
            (
                str(alarm.id),
                alarm.fire_at.strftime(TIME_FORMAT),
                alarm.state.value,
                alarm.resolved_at.strftime(TIME_FORMAT),
                alarm.message or NO_MESSAGE,
            )
            for alarm in alarms
        ],
    )


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Columns padded to their widest cell, two spaces between them.

    Written by hand because `rich` is a runtime dependency and DR-4 says no.
    """
    widths = [
        max(len(header), *(len(row[column]) for row in rows))
        for column, header in enumerate(headers)
    ]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip()
        for line in (headers, *rows)
    ]
    return "\n".join(lines)


def _clean(message: str | None) -> str | None:
    """An all-whitespace message is no message."""
    if message is None:
        return None
    stripped = message.strip()
    return stripped or None


def _fail(message: str) -> int:
    print(f"alarm: {message}", file=sys.stderr)
    return 1


def _warn_if_no_daemon(root: Path | None) -> None:
    """FR-11: warn on stderr when nothing is running to ring what we just wrote.

    A stub until M5: liveness means reading the PID file and testing it with
    `os.kill(pid, 0)`, which is the daemon's business and does not exist yet.
    Deliberately silent rather than guessing from the file's presence — a stale
    PID file would make it lie in the reassuring direction.
    """
    return None


# --- the surface -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="Set a one-off alarm for a clock time and get interrupted when it fires.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    add = commands.add_parser(
        "add",
        help="set an alarm for the next occurrence of a clock time",
        description=(
            "Set an alarm for the next occurrence of HH:MM: today if that time is "
            "still ahead, tomorrow otherwise."
        ),
    )
    add.add_argument("time", metavar="HH:MM", help=f"when to ring — {ACCEPTED_FORMAT}")
    add.add_argument("-m", "--message", help="what to show in the notification")
    add.set_defaults(handler=cmd_add)

    listing = commands.add_parser(
        "list",
        help="list armed alarms",
        description="List armed alarms, soonest first.",
    )
    listing.add_argument(
        "--all",
        action="store_true",
        help="also list alarms that fired, were missed, or were cancelled",
    )
    listing.set_defaults(handler=cmd_list)

    cancel = commands.add_parser(
        "cancel",
        help="cancel an armed alarm by id",
        description="Cancel an armed alarm. Its id is never reused.",
    )
    cancel.add_argument("id", metavar="ID", type=int, help="the id shown by `alarm list`")
    cancel.set_defaults(handler=cmd_cancel)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> int:
    """Run one command. `now` and `root` are the seams tests drive this through."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "handler", None) is None:
        # Invoked bare, the only useful thing to do is say what the commands are.
        parser.print_help(sys.stderr)
        return 2

    # The clock is read exactly once per run, so every timestamp a single
    # command writes agrees with every other.
    when = now if now is not None else datetime.now().astimezone()

    try:
        return args.handler(args, when, root)
    except (TimeFormatError, StoreError) as exc:
        # Errors the user can fix: a message, exit 1, no traceback. Anything
        # else is a bug and keeps its traceback.
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
