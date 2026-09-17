"""M5: the wake target, the due/missed decision, the PID file, and one daemon.

Everything here is a unit test against a fixed `now` except the last section,
which starts one real detached daemon — the single place real processes are
acceptable (TD-1). Nothing plays audio: the integration test puts fake players
on an otherwise empty PATH.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from alarm_cli import daemon, paths, store
from alarm_cli.daemon import DaemonError, is_alive, read_pid, seconds_to_next_minute, sweep
from alarm_cli.model import AlarmState

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 17, 7, 0, tzinfo=IST)


class Ringer:
    """Stands in for `notify.ring`, remembering what it was asked to ring."""

    def __init__(self, raises=None, before_ring=None):
        self.calls = []
        self.raises = raises
        self.before_ring = before_ring

    def __call__(self, message=None, root=None):
        self.calls.append((message, root))
        if self.before_ring is not None:
            self.before_ring()
        if self.raises is not None:
            raise self.raises

    @property
    def messages(self):
        return [message for message, _ in self.calls]


def arm(root, *, fire_at, message=None, state=AlarmState.ARMED, resolved_at=None):
    with store.transaction(root) as alarms:
        alarm = alarms.add(fire_at=fire_at, created_at=NOW - timedelta(hours=1), message=message)
        if state is not AlarmState.ARMED:
            alarms.update(alarm.resolve(state, resolved_at or NOW))
    return alarm.id


def state_of(root, alarm_id):
    return store.load(root).get(alarm_id).state


# --- the wake target -------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (NOW.replace(second=0, microsecond=0), 60.0),
        (NOW.replace(second=30), 30.0),
        (NOW.replace(second=59, microsecond=999_000), 0.001),
        (NOW.replace(second=59, microsecond=999_999), 0.000001),
        (NOW.replace(second=0, microsecond=1), 59.999999),
    ],
)
def test_seconds_to_next_minute(now, expected):
    assert seconds_to_next_minute(now) == pytest.approx(expected)


def test_the_wake_target_is_never_zero_or_negative():
    # A zero timeout on the boundary would spin: sweep, return instantly,
    # sweep again, for a whole second.
    for microsecond in (0, 1, 500_000, 999_999):
        for second in (0, 30, 59):
            now = NOW.replace(second=second, microsecond=microsecond)
            assert 0 < seconds_to_next_minute(now) <= 60


# --- the state machine -----------------------------------------------------


def test_an_alarm_that_is_not_due_is_left_alone(tmp_path):
    alarm_id = arm(tmp_path, fire_at=NOW + timedelta(minutes=1))
    ring = Ringer()

    assert sweep(NOW, tmp_path, ring=ring) == []
    assert state_of(tmp_path, alarm_id) is AlarmState.ARMED
    assert ring.calls == []


def test_an_alarm_due_this_instant_rings(tmp_path):
    alarm_id = arm(tmp_path, fire_at=NOW, message="standup")
    ring = Ringer()

    sweep(NOW, tmp_path, ring=ring)

    assert state_of(tmp_path, alarm_id) is AlarmState.FIRED
    assert ring.calls == [("standup", tmp_path)]


@pytest.mark.parametrize("overdue", [timedelta(seconds=1), timedelta(seconds=119), daemon.GRACE])
def test_an_alarm_within_the_grace_window_rings(tmp_path, overdue):
    # A wake that slipped, or one lost entirely, still rings.
    alarm_id = arm(tmp_path, fire_at=NOW - overdue)
    ring = Ringer()

    sweep(NOW, tmp_path, ring=ring)

    assert state_of(tmp_path, alarm_id) is AlarmState.FIRED
    assert len(ring.calls) == 1


@pytest.mark.parametrize(
    "overdue",
    [daemon.GRACE + timedelta(seconds=1), timedelta(hours=3), timedelta(days=1)],
)
def test_an_alarm_beyond_the_grace_window_is_missed_and_never_rings(tmp_path, overdue):
    # FR-9, DR-3: firing hours late is worse than not firing.
    alarm_id = arm(tmp_path, fire_at=NOW - overdue)
    ring = Ringer()

    sweep(NOW, tmp_path, ring=ring)

    assert state_of(tmp_path, alarm_id) is AlarmState.MISSED
    assert ring.calls == []


@pytest.mark.parametrize("state", [AlarmState.FIRED, AlarmState.MISSED, AlarmState.CANCELLED])
def test_an_alarm_already_in_a_terminal_state_is_not_touched(tmp_path, state):
    resolved_at = NOW - timedelta(days=1)
    alarm_id = arm(tmp_path, fire_at=NOW - timedelta(days=1), state=state, resolved_at=resolved_at)
    ring = Ringer()

    assert sweep(NOW, tmp_path, ring=ring) == []
    assert store.load(tmp_path).get(alarm_id).resolved_at == resolved_at
    assert ring.calls == []


def test_one_sweep_settles_every_alarm(tmp_path):
    later = arm(tmp_path, fire_at=NOW + timedelta(hours=1))
    due = arm(tmp_path, fire_at=NOW - timedelta(seconds=30), message="tea")
    overdue = arm(tmp_path, fire_at=NOW - timedelta(hours=3))
    ring = Ringer()

    changed = sweep(NOW, tmp_path, ring=ring)

    assert [alarm.id for alarm in changed] == [due, overdue]
    assert state_of(tmp_path, later) is AlarmState.ARMED
    assert state_of(tmp_path, due) is AlarmState.FIRED
    assert state_of(tmp_path, overdue) is AlarmState.MISSED
    assert ring.messages == ["tea"]


def test_the_resolved_time_is_the_sweep_time(tmp_path):
    alarm_id = arm(tmp_path, fire_at=NOW - timedelta(seconds=30))
    sweep(NOW, tmp_path, ring=Ringer())
    assert store.load(tmp_path).get(alarm_id).resolved_at == NOW


def test_a_sweep_with_nothing_to_do_does_not_write(tmp_path):
    arm(tmp_path, fire_at=NOW + timedelta(hours=1))
    before = paths.alarms_json(tmp_path).stat().st_mtime_ns

    sweep(NOW, tmp_path, ring=Ringer())

    # NFR-4: 1,440 wakes a day, and almost all of them have nothing to do.
    assert paths.alarms_json(tmp_path).stat().st_mtime_ns == before


def test_a_sweep_of_an_empty_store_is_harmless(tmp_path):
    assert sweep(NOW, tmp_path, ring=Ringer()) == []


def test_the_alarm_is_committed_before_it_rings(tmp_path):
    # No lock is held across a subprocess, and a crash mid-ring must not leave
    # the alarm armed to ring again on the next wake.
    alarm_id = arm(tmp_path, fire_at=NOW, message="standup")
    seen = []
    ring = Ringer(before_ring=lambda: seen.append(state_of(tmp_path, alarm_id)))

    sweep(NOW, tmp_path, ring=ring)

    assert seen == [AlarmState.FIRED]


def test_a_ring_that_raises_does_not_stop_the_sweep(tmp_path, caplog):
    first = arm(tmp_path, fire_at=NOW, message="boom")
    second = arm(tmp_path, fire_at=NOW, message="also me")
    ring = Ringer(raises=RuntimeError("the speaker exploded"))

    with caplog.at_level(logging.ERROR):
        sweep(NOW, tmp_path, ring=ring)

    assert state_of(tmp_path, first) is AlarmState.FIRED
    assert state_of(tmp_path, second) is AlarmState.FIRED
    assert ring.messages == ["boom", "also me"]
    assert "ringing alarm" in caplog.text


def test_a_ring_and_a_miss_are_both_logged(tmp_path, caplog):
    arm(tmp_path, fire_at=NOW, message="standup")
    arm(tmp_path, fire_at=NOW - timedelta(hours=3))

    with caplog.at_level(logging.INFO):
        sweep(NOW, tmp_path, ring=Ringer())

    assert "ringing" in caplog.text
    assert "missed, not ringing" in caplog.text


# --- the loop --------------------------------------------------------------


def test_the_loop_sweeps_and_stops_when_asked(tmp_path):
    alarm_id = arm(tmp_path, fire_at=NOW, message="standup")
    stop_event = threading.Event()
    ticks = []

    def clock():
        ticks.append(NOW)
        if len(ticks) >= 2:
            stop_event.set()  # set before the wait, so the wait returns at once
        return NOW

    daemon.run(tmp_path, stop_event=stop_event, ring=Ringer(), clock=clock)

    assert state_of(tmp_path, alarm_id) is AlarmState.FIRED
    assert len(ticks) == 2  # one for the sweep, one for the wake target


def test_a_loop_asked_to_stop_before_it_starts_does_nothing(tmp_path):
    arm(tmp_path, fire_at=NOW)
    stop_event = threading.Event()
    stop_event.set()

    daemon.run(tmp_path, stop_event=stop_event, ring=Ringer(), clock=lambda: NOW)

    assert store.load(tmp_path).armed()


def test_a_store_broken_by_hand_does_not_kill_the_daemon(tmp_path, caplog):
    paths.ensure_root(tmp_path)
    paths.alarms_json(tmp_path).write_text("{not json", encoding="utf-8")
    stop_event = threading.Event()
    ticks = []

    def clock():
        ticks.append(NOW)
        if len(ticks) >= 2:
            stop_event.set()
        return NOW

    with caplog.at_level(logging.ERROR):
        daemon.run(tmp_path, stop_event=stop_event, ring=Ringer(), clock=clock)

    # It keeps waking, so it is still there when the user fixes the file.
    assert "not valid JSON" in caplog.text


# --- the PID file ----------------------------------------------------------


def test_no_pid_file_means_no_pid(tmp_path):
    assert read_pid(tmp_path) is None
    assert daemon.status(tmp_path) is None


def test_a_pid_file_that_is_not_a_number_is_ignored(tmp_path):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("not a pid\n", encoding="utf-8")
    assert read_pid(tmp_path) is None


def test_a_pid_file_is_read_as_an_integer(tmp_path):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text(" 4321 \n", encoding="utf-8")
    assert read_pid(tmp_path) == 4321


def test_this_process_is_alive():
    assert is_alive(os.getpid())


def test_a_process_that_has_exited_is_not_alive():
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child never returns to pytest
        os._exit(0)
    os.waitpid(pid, 0)
    assert not is_alive(pid)


@pytest.mark.parametrize("pid", [0, -1, -4321])
def test_a_process_group_is_never_mistaken_for_a_process(pid):
    # os.kill(0, ...) signals *this whole process group*, pytest included.
    assert not is_alive(pid)


def test_status_reports_a_live_daemon(tmp_path):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert daemon.status(tmp_path) == os.getpid()


def test_status_clears_a_pid_file_that_outlived_its_process(tmp_path, monkeypatch):
    # A PID file in $HOME survives a reboot, so the file proves nothing (DR-5).
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)

    assert daemon.status(tmp_path) is None
    assert not paths.pid_file(tmp_path).exists()


# --- start and stop, without forking ---------------------------------------


def test_start_refuses_when_a_daemon_is_already_running(tmp_path, monkeypatch):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "is_alive", lambda pid: True)
    monkeypatch.setattr(
        daemon, "_detach", lambda root: pytest.fail("a second daemon was started")
    )

    with pytest.raises(DaemonError, match="already running \\(pid 4321\\)"):
        daemon.start(tmp_path)


def test_stopping_nothing_reports_nothing(tmp_path):
    assert daemon.stop(tmp_path) is None


def test_stopping_a_stale_pid_file_clears_it(tmp_path, monkeypatch):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)

    assert daemon.stop(tmp_path) is None
    assert not paths.pid_file(tmp_path).exists()


def test_stop_signals_the_daemon_and_clears_the_file(tmp_path, monkeypatch):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    signalled = []
    alive = {"yes": True}

    def fake_kill(pid, sig):
        signalled.append((pid, sig))
        alive["yes"] = False

    monkeypatch.setattr(daemon.os, "kill", fake_kill)
    monkeypatch.setattr(daemon, "is_alive", lambda pid: alive["yes"])

    assert daemon.stop(tmp_path) == 4321
    assert signalled == [(4321, signal.SIGTERM)]
    assert not paths.pid_file(tmp_path).exists()


def test_a_daemon_that_will_not_die_is_reported_not_hidden(tmp_path, monkeypatch):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon, "is_alive", lambda pid: True)

    with pytest.raises(DaemonError, match="did not stop within"):
        daemon.stop(tmp_path, timeout=0.05)

    # The file stays: something is still running, and status must keep saying so.
    assert paths.pid_file(tmp_path).exists()


# --- the one integration test (TD-1) ---------------------------------------


def _fake_binaries(directory: Path) -> Path:
    """A PATH holding a player and a notifier that do nothing audible.

    Both are symlinks to `echo`: real binaries that succeed and print, so the
    daemon logs the ring it managed. Symlinks rather than shell scripts
    because a temp directory is often mounted `noexec`, and a stub that cannot
    be executed would fail this test for a reason that has nothing to do with
    the daemon.
    """
    echo = shutil.which("echo")
    if echo is None:  # pragma: no cover - no POSIX machine is missing echo
        pytest.skip("no `echo` to stand in for a sound player")

    directory.mkdir(parents=True, exist_ok=True)
    for name in ("paplay", "notify-send"):
        (directory / name).symlink_to(echo)
    return directory


def _alarm(root: Path, path_dir: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alarm_cli.cli", *argv],
        capture_output=True,
        text=True,
        timeout=30,
        # PATH holds only the fakes, so nothing real can be played even if the
        # machine running these tests has a sound card.
        env={"PATH": str(path_dir), "ALARM_CLI_HOME": str(root)},
    )


def _until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_real_daemon_detaches_rings_and_stops_promptly(tmp_path):
    """Start a real daemon, watch an alarm reach `fired`, stop it.

    The single test that spawns processes (TD-1). It covers the three things
    no unit test can: that the daemon outlives the command that started it,
    that a ring actually reaches a player, and that `stop` does not wait out
    the current minute.
    """
    root = tmp_path / "home"
    fakes = _fake_binaries(tmp_path / "bin")

    # Armed for the top of this minute, so it is already due and the daemon's
    # startup sweep fires it — no waiting for a boundary to come round.
    now = datetime.now().astimezone()
    with store.transaction(root) as alarms:
        alarms.add(fire_at=now.replace(second=0, microsecond=0), created_at=now, message="standup")

    started = _alarm(root, fakes, "daemon", "start")
    assert started.returncode == 0, started.stderr
    assert "daemon started" in started.stdout

    pid = read_pid(root)
    assert pid is not None
    try:
        # The starting command has exited and the daemon is still running: it
        # is not a child of this process, and closing the shell cannot take it.
        assert is_alive(pid)

        fired = _until(
            lambda: json.loads(paths.alarms_json(root).read_text())["alarms"][0]["state"] == "fired"
        )
        assert fired, paths.log_file(root).read_text()

        # The ring reached both binaries and both succeeded (NFR-8 logs it).
        log_text = paths.log_file(root).read_text()
        assert "ran paplay" in log_text, log_text
        assert "ran notify-send -u critical Alarm standup" in log_text, log_text
        assert paths.wav_file(root).is_file()  # the tone was generated to play

        status = _alarm(root, fakes, "daemon", "status")
        assert f"pid {pid}" in status.stdout

        # The PEP 475 trap: with time.sleep() and a flag-setting handler this
        # would block until the next minute boundary, up to 60 seconds.
        before = time.monotonic()
        stopped = _alarm(root, fakes, "daemon", "stop")
        elapsed = time.monotonic() - before

        assert stopped.returncode == 0, stopped.stderr
        assert elapsed < 15, f"stop took {elapsed:.1f}s — is the loop sleeping?"
        assert _until(lambda: not is_alive(pid))
        assert not paths.pid_file(root).exists()
        assert "daemon stopping" in paths.log_file(root).read_text()
    finally:
        if is_alive(pid):  # pragma: no cover - only on a failed run
            os.kill(pid, signal.SIGKILL)
