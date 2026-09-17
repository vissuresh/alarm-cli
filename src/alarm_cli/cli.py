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

from alarm_cli import __version__, daemon, store
from alarm_cli.daemon import DaemonError
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


def cmd_daemon_start(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-6: exactly one detached daemon, or a refusal naming the live one."""
    pid = daemon.start(root)
    print(f"daemon started (pid {pid})")
    return 0


def cmd_daemon_stop(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-7: signal the daemon, wait for it to go, clear the PID file."""
    pid = daemon.stop(root)
    if pid is None:
        return _fail("no daemon is running")
    print(f"daemon stopped (pid {pid})")
    return 0


def cmd_daemon_status(args: argparse.Namespace, now: datetime, root: Path | None) -> int:
    """FR-7: report, and clear a PID file that outlived its process.

    Exit 0 either way — "not running" is a true answer to the question asked,
    not a failure to answer it.
    """
    pid = daemon.status(root)
    print(f"daemon is running (pid {pid})" if pid else "no daemon is running")
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

    A warning, never a failure: the alarm is stored either way, and the user
    may well be about to start the daemon. `status` tests liveness rather than
    trusting the PID file, so a stale file cannot make this lie in the
    reassuring direction.
    """
    if daemon.status(root) is None:
        print(
            "alarm: warning: no daemon is running, so nothing will ring — "
            "start one with `alarm daemon start`",
            file=sys.stderr,
        )


# --- the surface -----------------------------------------------------------


#: Shown at the foot of `alarm --help`. The daemon requirement is the one thing
#: a new user has to know and cannot guess (DR-2).
EPILOG = """\
Alarms ring only while the daemon is running, and it is never started for you:

  alarm daemon start            once per login session
  alarm add 07:00 -m standup    the next 07:00 — today if it is still ahead
  alarm list                    what is armed, soonest first
  alarm cancel 1                by the id `list` shows

State lives in ~/.alarm-cli/ (set ALARM_CLI_HOME to keep it elsewhere):
alarms.json is the alarms, daemon.log is what the daemon did, and alarm.wav is
the tone — replace it with any WAV you prefer.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="Set a one-off alarm for a clock time and get interrupted when it fires.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        # Hard-wrapped, because the raw formatter the epilog needs also turns
        # off wrapping for the description.
        description=(
            "Set an alarm for the next occurrence of HH:MM: today if that time\n"
            "is still ahead, tomorrow otherwise. The resolved date is printed,\n"
            "so you can see which day it landed on."
        ),
        epilog="Examples:\n  alarm add 07:00 -m standup\n  alarm add 14:30\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add.add_argument("time", metavar="HH:MM", help=f"when to ring — {ACCEPTED_FORMAT}")
    add.add_argument("-m", "--message", help="what to show in the notification")
    add.set_defaults(handler=cmd_add)

    listing = commands.add_parser(
        "list",
        help="list armed alarms",
        description=(
            "List armed alarms, soonest first. With --all, every alarm this store "
            "has ever held: fired, missed (came due with no daemon running) and "
            "cancelled, each with the time it reached that state."
        ),
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
        description=(
            "Cancel an armed alarm. Ids are never reused, so a cancelled id in your "
            "shell history can never later hit a different alarm."
        ),
    )
    cancel.add_argument("id", metavar="ID", type=int, help="the id shown by `alarm list`")
    cancel.set_defaults(handler=cmd_cancel)

    daemon_parser = commands.add_parser(
        "daemon",
        help="start, stop or query the background process that rings alarms",
        description=(
            "Manage the daemon. Alarms only ring while it is running; it is never "
            "started implicitly. It survives the terminal that started it, but not "
            "a reboot — start it again after one."
        ),
    )
    daemon_commands = daemon_parser.add_subparsers(dest="daemon_command", metavar="COMMAND")
    daemon_commands.add_parser(
        "start", help="detach a daemon and leave it running"
    ).set_defaults(handler=cmd_daemon_start)
    daemon_commands.add_parser(
        "stop", help="ask the running daemon to exit"
    ).set_defaults(handler=cmd_daemon_stop)
    daemon_commands.add_parser(
        "status", help="say whether a daemon is running, and its pid"
    ).set_defaults(handler=cmd_daemon_status)
    # `alarm daemon` with no verb: say what the verbs are, like a bare `alarm`.
    daemon_parser.set_defaults(usage_parser=daemon_parser)

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
        getattr(args, "usage_parser", parser).print_help(sys.stderr)
        return 2

    # The clock is read exactly once per run, so every timestamp a single
    # command writes agrees with every other.
    when = now if now is not None else datetime.now().astimezone()

    try:
        return args.handler(args, when, root)
    except (TimeFormatError, StoreError, DaemonError) as exc:
        # Errors the user can fix: a message, exit 1, no traceback. Anything
        # else is a bug and keeps its traceback.
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
