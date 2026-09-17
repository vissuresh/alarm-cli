"""Detachment, the PID file, the wake loop, and the due/missed decision.

Wakes on the wall-clock minute boundary rather than on an interval, waits on a
``threading.Event`` so SIGTERM is seen immediately (PEP 475), and formats no
user-facing output — it returns values and raises :class:`DaemonError`, and
``cli`` decides what the user reads.

The double fork is the load-bearing part: after ``setsid`` the daemon is in its
own session with no controlling terminal, so the SIGHUP that closing a shell
sends never reaches it. If that breaks, everything else here is decoration.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from alarm_cli import notify, paths, store
from alarm_cli.model import Alarm, AlarmState
from alarm_cli.store import StoreError

log = logging.getLogger(__name__)

#: How late an alarm may be and still ring. Two wake periods (DR-9): enough to
#: absorb one wake lost entirely, short enough that anything beyond it is a
#: suspend or a restart rather than jitter.
GRACE = timedelta(seconds=120)

#: How long `stop` waits for the daemon to go away before giving up on it.
STOP_TIMEOUT_SECONDS = 10.0

#: How long `start` waits for the detached daemon to publish its PID.
START_TIMEOUT_SECONDS = 5.0

_POLL_SECONDS = 0.02

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class DaemonError(Exception):
    """Something the user can act on: already running, or refusing to stop."""


# --- the decision ----------------------------------------------------------


def seconds_to_next_minute(now: datetime) -> float:
    """How long to wait for the next wall-clock minute boundary.

    A pure function of `now`, recomputed every iteration and never accumulated,
    so NTP steps, scheduling jitter and a slow sweep are absorbed by the next
    computation instead of compounding into drift. At an exact boundary this is
    a full 60 seconds, not zero — the boundary we are standing on has already
    been swept.
    """
    return 60 - now.second - now.microsecond / 1e6


def sweep(
    now: datetime,
    root: Path | str | None = None,
    *,
    ring: Callable[..., None] = notify.ring,
) -> list[Alarm]:
    """Fire what is due, miss what is too late, leave the rest armed.

    The whole of the miss detection (FR-9): it runs at startup and on every
    wake, so there is no separate startup path to keep in sync.

    Returns the alarms that changed, in the state they ended up in.
    """
    changed: list[Alarm] = []

    with store.transaction(root) as alarms:
        for alarm in alarms.armed():
            overdue = now - alarm.fire_at
            if overdue < timedelta(0):
                continue  # not yet
            state = AlarmState.FIRED if overdue <= GRACE else AlarmState.MISSED
            resolved = alarm.resolve(state, now)
            alarms.update(resolved)
            changed.append(resolved)

    # Ringing happens with the lock released and the new state already on disk.
    # A ring can take seconds, and no store write may wait behind a subprocess.
    for alarm in changed:
        if alarm.state is AlarmState.FIRED:
            log.info("alarm %s due (%s) — ringing", alarm.id, alarm.message or "no message")
            _ring(alarm, root, ring)
        else:
            log.info(
                "alarm %s was due at %s and is overdue by more than %ss — missed, not ringing",
                alarm.id,
                alarm.fire_at.isoformat(),
                int(GRACE.total_seconds()),
            )

    return changed


def _ring(alarm: Alarm, root: Path | str | None, ring: Callable[..., None]) -> None:
    """`notify.ring` promises never to raise; this is the belt to that braces.

    The alarm is already `fired` on disk. Letting anything escape here would
    cost every later alarm in this sweep, to no benefit (TD-4).
    """
    try:
        ring(alarm.message, root)
    except Exception:  # noqa: BLE001
        log.exception("ringing alarm %s failed", alarm.id)


# --- the loop --------------------------------------------------------------


def run(
    root: Path | str | None = None,
    *,
    stop_event: threading.Event | None = None,
    ring: Callable[..., None] = notify.ring,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> None:
    """Sweep, then wait for the next minute boundary, until asked to stop."""
    stop_event = stop_event if stop_event is not None else threading.Event()
    log.info("daemon started (pid %s)", os.getpid())

    while not stop_event.is_set():
        try:
            sweep(clock(), root, ring=ring)
        except StoreError as exc:
            # A store the user has broken by hand. Keep waking: nothing can
            # ring until it is fixed, but the daemon should still be there
            # when it is.
            log.error("%s", exc)

        # Recomputed from the clock, and waited on an Event rather than slept:
        # a flag-setting SIGTERM handler plus time.sleep() would leave the
        # daemon sleeping out the rest of its minute (PEP 475, DR-9).
        stop_event.wait(seconds_to_next_minute(clock()))

    log.info("daemon stopping (pid %s)", os.getpid())


# --- the PID file ----------------------------------------------------------


def read_pid(root: Path | str | None = None) -> int | None:
    """The PID in the file, or None if it is absent or unreadable."""
    try:
        text = paths.pid_file(root).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def is_alive(pid: int) -> bool:
    """Whether a process with this PID exists and we may signal it.

    `os.kill(pid, 0)` delivers nothing; it only asks the question. A PID we do
    not own raises PermissionError, which still answers "yes, it exists".
    """
    if pid <= 0:
        # 0 and negatives address process *groups*; never ask about those.
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def status(root: Path | str | None = None) -> int | None:
    """The live daemon's PID, or None. Clears a PID file that outlived it.

    A PID file in `$HOME` survives a reboot (DR-5), so the file's existence
    proves nothing and liveness is always tested rather than trusted.
    """
    pid = read_pid(root)
    if pid is None:
        return None
    if is_alive(pid):
        return pid

    log.info("removing a stale pid file for pid %s", pid)
    paths.pid_file(root).unlink(missing_ok=True)
    return None


def _write_pid(root: Path | str | None) -> None:
    paths.pid_file(root).write_text(f"{os.getpid()}\n", encoding="utf-8")


# --- lifecycle -------------------------------------------------------------


def start(root: Path | str | None = None) -> int:
    """Detach a daemon and return its PID. Refuses if one is already live."""
    running = status(root)
    if running is not None:
        raise DaemonError(f"daemon already running (pid {running})")

    # Resolved before the fork, because the daemon chdirs to / and a relative
    # root would then point somewhere else entirely.
    resolved = paths.ensure_root(root).resolve()
    return _detach(resolved)


def stop(root: Path | str | None = None, timeout: float = STOP_TIMEOUT_SECONDS) -> int | None:
    """SIGTERM the daemon, wait for it to go, clear the PID file.

    Returns the PID it stopped, or None if nothing was running.
    """
    pid = status(root)
    if pid is None:
        return None

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        paths.pid_file(root).unlink(missing_ok=True)
        return None

    if not _wait_until(lambda: not is_alive(pid), timeout):
        raise DaemonError(
            f"daemon (pid {pid}) did not stop within {timeout:g}s; "
            f"send it SIGKILL by hand if it is wedged"
        )

    paths.pid_file(root).unlink(missing_ok=True)
    return pid


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_SECONDS)
    return predicate()


# --- detachment ------------------------------------------------------------


def _detach(root: Path) -> int:
    """Double-fork into a new session and return the daemon's PID.

    In the intermediate child and the daemon this never returns: both leave
    through `os._exit`, so no `finally` belonging to the caller — a shell, a
    test runner — can run twice.
    """
    first = os.fork()
    if first > 0:
        # The original process. The intermediate child exits immediately;
        # reaping it here keeps `alarm daemon start` from leaving a zombie.
        os.waitpid(first, 0)
        pid = _await_pid_file(root)
        if pid is None:
            raise DaemonError(
                f"the daemon did not start; look in {paths.log_file(root)}"
            )
        return pid

    try:
        # The intermediate child. setsid() makes it a session leader with no
        # controlling terminal; the second fork means the daemon is not a
        # session leader, so it can never acquire one by opening a tty.
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
        _be_the_daemon(root)
    except BaseException:  # noqa: BLE001 - nothing may escape back up the fork
        os._exit(1)
    os._exit(0)


def _be_the_daemon(root: Path) -> None:
    os.chdir("/")  # so the daemon never pins a directory the user wants to delete
    _redirect_stdio(root)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stderr)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    _write_pid(root)
    try:
        _run_logging_failures(root, stop_event)
    finally:
        paths.pid_file(root).unlink(missing_ok=True)


def _run_logging_failures(root: Path, stop_event: threading.Event) -> None:
    """Run the loop, and make sure a bug leaves a traceback behind.

    The daemon leaves through `os._exit`, which runs no handlers and prints
    nothing — so a crash is written here or it is written nowhere, and a
    daemon that vanished without a word is the worst thing to debug at 07:00
    (DR-16, NFR-8).
    """
    try:
        run(root, stop_event=stop_event)
    except BaseException:
        log.exception("daemon exiting on an unhandled error")
        raise


def _redirect_stdio(root: Path) -> None:
    """Point the daemon's three descriptors at /dev/null and `daemon.log`.

    Both a courtesy and a necessity: an inherited terminal would keep that
    terminal open, and a traceback with nowhere to go is a daemon that dies
    without saying why (NFR-8).
    """
    sys.stdout.flush()
    sys.stderr.flush()

    devnull = os.open(os.devnull, os.O_RDONLY)
    logfile = os.open(paths.log_file(root), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.dup2(devnull, 0)
        os.dup2(logfile, 1)
        os.dup2(logfile, 2)
    finally:
        os.close(devnull)
        os.close(logfile)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def handle(signum, _frame):
        # Only sets a flag: the Event the loop waits on returns at once, and
        # the current sweep is left to finish rather than being cut in half.
        log.info("caught %s", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)


def _await_pid_file(root: Path, timeout: float = START_TIMEOUT_SECONDS) -> int | None:
    """Wait for the daemon to publish a PID we can report and verify."""
    pid: int | None = None

    def published() -> bool:
        nonlocal pid
        pid = read_pid(root)
        return pid is not None and is_alive(pid)

    if _wait_until(published, timeout):
        return pid
    return None
