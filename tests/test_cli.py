"""M3: the client commands — FR-1 through FR-5, and the exit codes.

Every command is driven through `main` with `now` and the store root pinned, so
nothing here reads the clock or touches a real `~/.alarm-cli`.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from alarm_cli import daemon, paths, store
from alarm_cli.cli import format_delta, main
from alarm_cli.model import AlarmState

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 16, 22, 48, 11, tzinfo=IST)


@pytest.fixture
def run(tmp_path):
    """Run one command against a throwaway store at a fixed instant."""

    def _run(*argv, now=NOW):
        return main(list(argv), now=now, root=tmp_path)

    return _run


@pytest.fixture
def alarms(tmp_path):
    def _alarms():
        return store.load(tmp_path)

    return _alarms


# --- FR-1: add -------------------------------------------------------------


def test_add_stores_an_armed_alarm_for_the_next_occurrence(run, alarms, capsys):
    assert run("add", "07:00", "-m", "standup") == 0

    (alarm,) = alarms().alarms
    assert alarm.id == 1
    assert alarm.state is AlarmState.ARMED
    assert alarm.fire_at == datetime(2026, 9, 17, 7, 0, tzinfo=IST)
    assert alarm.created_at == NOW
    assert alarm.message == "standup"
    assert alarm.resolved_at is None


def test_add_prints_the_resolved_absolute_time_and_the_wait(run, capsys):
    run("add", "07:00", "-m", "standup")
    assert capsys.readouterr().out == "alarm 1 set for 2026-09-17 07:00 (in 8h 11m)\n"


def test_add_resolves_to_today_when_the_time_is_still_ahead(run, alarms):
    run("add", "23:30")
    assert alarms().alarms[0].fire_at == datetime(2026, 9, 16, 23, 30, tzinfo=IST)


def test_add_without_a_message_stores_none(run, alarms):
    run("add", "07:00")
    assert alarms().alarms[0].message is None


def test_add_treats_a_blank_message_as_no_message(run, alarms):
    run("add", "07:00", "-m", "   ")
    assert alarms().alarms[0].message is None


def test_add_allocates_the_next_id(run, capsys):
    run("add", "07:00")
    run("add", "09:00")
    assert capsys.readouterr().out.splitlines()[1].startswith("alarm 2 set")


def test_add_accepts_the_long_message_flag(run, alarms):
    run("add", "07:00", "--message", "standup")
    assert alarms().alarms[0].message == "standup"


# --- FR-2: add rejects a malformed time ------------------------------------


@pytest.mark.parametrize("bad", ["7:00", "25:00", "07:60", "0700", "abc"])
def test_add_rejects_a_malformed_time_without_touching_the_store(run, tmp_path, capsys, bad):
    assert run("add", bad) == 1

    err = capsys.readouterr().err
    assert repr(bad) in err
    assert "HH:MM in 24-hour form" in err  # names what would have worked
    assert not paths.alarms_json(tmp_path).exists()


def test_a_malformed_time_leaves_existing_alarms_alone(run, tmp_path):
    run("add", "07:00")
    before = paths.alarms_json(tmp_path).read_text(encoding="utf-8")

    assert run("add", "25:00") == 1
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == before


def test_add_needs_a_time(run):
    # argparse's own error: exit 2, not 1.
    with pytest.raises(SystemExit) as exc:
        run("add")
    assert exc.value.code == 2


# --- FR-3: list ------------------------------------------------------------


def test_list_prints_id_time_remaining_and_message(run, capsys):
    run("add", "07:00", "-m", "standup")
    capsys.readouterr()

    assert run("list") == 0
    assert capsys.readouterr().out == (
        "ID  FIRES AT          IN      MESSAGE\n"
        "1   2026-09-17 07:00  8h 11m  standup\n"
    )


def test_list_orders_by_fire_time_not_by_id(run, capsys):
    run("add", "09:00")  # tomorrow
    run("add", "23:30")  # today
    capsys.readouterr()

    run("list")
    ids = [line.split()[0] for line in capsys.readouterr().out.splitlines()[1:]]
    assert ids == ["2", "1"]


def test_list_shows_a_dash_for_an_alarm_with_no_message(run, capsys):
    run("add", "07:00")
    capsys.readouterr()

    run("list")
    assert capsys.readouterr().out.splitlines()[1].endswith("-")


def test_list_says_so_when_nothing_is_armed(run, capsys):
    assert run("list") == 0
    assert capsys.readouterr().out == "no armed alarms\n"


def test_list_hides_alarms_that_are_no_longer_armed(run, capsys):
    run("add", "07:00")
    run("add", "09:00")
    run("cancel", "1")
    capsys.readouterr()

    run("list")
    out = capsys.readouterr().out
    assert "09:00" in out
    assert "07:00" not in out


def test_list_marks_an_alarm_that_came_due_with_nothing_running(run, capsys):
    run("add", "23:30")
    capsys.readouterr()

    # Half an hour later, with no daemon to have rung it.
    run("list", now=datetime(2026, 9, 17, 0, 0, tzinfo=IST))
    assert "due" in capsys.readouterr().out


# --- FR-4: list --all ------------------------------------------------------


def test_list_all_shows_terminal_alarms_with_the_time_they_resolved(run, capsys):
    run("add", "07:00", "-m", "standup")
    run("add", "09:00")
    run("cancel", "2", now=datetime(2026, 9, 16, 23, 0, tzinfo=IST))
    capsys.readouterr()

    assert run("list", "--all") == 0
    assert capsys.readouterr().out == (
        "ID  FIRES AT          IN      MESSAGE\n"
        "1   2026-09-17 07:00  8h 11m  standup\n"
        "\n"
        "ID  FIRES AT          STATE      RESOLVED AT       MESSAGE\n"
        "2   2026-09-17 09:00  cancelled  2026-09-16 23:00  -\n"
    )


def test_list_all_orders_the_history_by_when_it_resolved(run, capsys):
    run("add", "07:00")
    run("add", "09:00")
    run("cancel", "2", now=datetime(2026, 9, 16, 23, 0, tzinfo=IST))
    run("cancel", "1", now=datetime(2026, 9, 16, 22, 50, tzinfo=IST))
    capsys.readouterr()

    run("list", "--all")
    history = capsys.readouterr().out.splitlines()[3:]
    assert [line.split()[0] for line in history] == ["1", "2"]


def test_list_all_says_so_when_there_is_no_history(run, capsys):
    run("add", "07:00")
    capsys.readouterr()

    run("list", "--all")
    assert capsys.readouterr().out.endswith("\nno past alarms\n")


def test_list_all_on_an_empty_store(run, capsys):
    assert run("list", "--all") == 0
    assert capsys.readouterr().out == "no armed alarms\n\nno past alarms\n"


def test_list_without_all_does_not_print_the_history(run, capsys):
    run("add", "07:00")
    run("cancel", "1")
    capsys.readouterr()

    run("list")
    assert capsys.readouterr().out == "no armed alarms\n"


# --- FR-5: cancel ----------------------------------------------------------


def test_cancel_moves_an_armed_alarm_to_cancelled(run, alarms, capsys):
    run("add", "07:00")
    capsys.readouterr()

    at = datetime(2026, 9, 16, 23, 0, tzinfo=IST)
    assert run("cancel", "1", now=at) == 0
    assert capsys.readouterr().out == "alarm 1 cancelled\n"

    alarm = alarms().get(1)
    assert alarm.state is AlarmState.CANCELLED
    assert alarm.resolved_at == at


def test_cancelling_an_unknown_id_changes_nothing(run, tmp_path, capsys):
    run("add", "07:00")
    before = paths.alarms_json(tmp_path).read_text(encoding="utf-8")
    capsys.readouterr()

    assert run("cancel", "9") == 1
    assert capsys.readouterr().err == "alarm: no alarm with id 9\n"
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == before


def test_cancelling_on_an_empty_store_changes_nothing(run, tmp_path):
    assert run("cancel", "1") == 1
    assert not paths.alarms_json(tmp_path).exists()


def test_cancelling_an_already_cancelled_alarm_is_refused(run, tmp_path, capsys):
    run("add", "07:00")
    run("cancel", "1")
    before = paths.alarms_json(tmp_path).read_text(encoding="utf-8")
    capsys.readouterr()

    assert run("cancel", "1") == 1
    assert "already cancelled" in capsys.readouterr().err
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == before


def test_cancelling_a_fired_alarm_is_refused(run, tmp_path, capsys):
    run("add", "07:00")
    with store.transaction(tmp_path) as target:
        target.update(target.get(1).resolve(AlarmState.FIRED, NOW))
    capsys.readouterr()

    assert run("cancel", "1") == 1
    assert "already fired" in capsys.readouterr().err


def test_cancel_needs_an_integer_id(run):
    with pytest.raises(SystemExit) as exc:
        run("cancel", "one")
    assert exc.value.code == 2


def test_a_cancelled_id_is_not_handed_to_a_later_alarm(run, alarms):
    run("add", "07:00")
    run("cancel", "1")
    run("add", "09:00")
    assert [alarm.id for alarm in alarms().alarms] == [1, 2]


# --- exit codes and error surfaces -----------------------------------------


def test_an_unknown_command_is_a_usage_error(run):
    with pytest.raises(SystemExit) as exc:
        run("snooze", "1")
    assert exc.value.code == 2


def test_a_corrupt_store_is_reported_not_repaired(run, tmp_path, capsys):
    paths.alarms_json(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    paths.alarms_json(tmp_path).write_text("{not json", encoding="utf-8")

    assert run("list") == 1
    err = capsys.readouterr().err
    assert str(paths.alarms_json(tmp_path)) in err  # where to look
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == "{not json"


def test_add_over_a_corrupt_store_does_not_overwrite_it(run, tmp_path, capsys):
    paths.alarms_json(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    paths.alarms_json(tmp_path).write_text("{not json", encoding="utf-8")

    assert run("add", "07:00") == 1
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == "{not json"


def test_a_bug_keeps_its_traceback(run, monkeypatch):
    # Errors the user did not cause are not swallowed into exit 1.
    def boom(*args, **kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(store, "load", boom)
    with pytest.raises(MemoryError):
        run("list")


def test_the_store_the_commands_write_is_the_documented_one(run, tmp_path):
    run("add", "07:00", "-m", "standup")
    raw = json.loads(paths.alarms_json(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["alarms"][0]["fire_at"] == "2026-09-17T07:00:00+05:30"


def test_commands_honour_the_environment_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    assert main(["add", "07:00"], now=NOW) == 0
    assert store.load(tmp_path).alarms[0].fire_at == datetime(2026, 9, 17, 7, 0, tzinfo=IST)


# --- the relative time column ----------------------------------------------


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(hours=8, minutes=12), "8h 12m"),
        (timedelta(hours=1, minutes=2), "1h 02m"),
        (timedelta(hours=1), "1h 00m"),
        (timedelta(minutes=42), "42m"),
        (timedelta(minutes=1), "1m"),
        (timedelta(seconds=59), "<1m"),
        (timedelta(seconds=1), "<1m"),
        (timedelta(0), "due"),
        (timedelta(minutes=-5), "due"),
        (timedelta(days=1, hours=3), "1d 03h"),
        # Truncated, not rounded: it is not yet 8h 13m away.
        (timedelta(hours=8, minutes=12, seconds=59), "8h 12m"),
    ],
)
def test_format_delta(delta, expected):
    assert format_delta(delta) == expected


# --- FR-6, FR-7: the daemon commands ---------------------------------------


def test_daemon_status_reports_a_running_daemon(run, tmp_path, capsys):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text(f"{os.getpid()}\n", encoding="utf-8")

    assert run("daemon", "status") == 0
    assert capsys.readouterr().out == f"daemon is running (pid {os.getpid()})\n"


def test_daemon_status_reports_nothing_running(run, capsys):
    # Not running is a true answer, not a failure to answer: exit 0.
    assert run("daemon", "status") == 0
    assert capsys.readouterr().out == "no daemon is running\n"


def test_daemon_status_clears_a_stale_pid_file(run, tmp_path, monkeypatch, capsys):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)

    assert run("daemon", "status") == 0
    assert not paths.pid_file(tmp_path).exists()


def test_daemon_start_prints_the_new_pid(run, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "start", lambda root: 4321)
    assert run("daemon", "start") == 0
    assert capsys.readouterr().out == "daemon started (pid 4321)\n"


def test_daemon_start_refuses_a_second_daemon(run, tmp_path, monkeypatch, capsys):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text(f"{os.getpid()}\n", encoding="utf-8")
    monkeypatch.setattr(
        daemon, "_detach", lambda root: pytest.fail("a second daemon was started")
    )

    assert run("daemon", "start") == 1
    assert f"already running (pid {os.getpid()})" in capsys.readouterr().err


def test_daemon_stop_reports_the_pid_it_stopped(run, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "stop", lambda root: 4321)
    assert run("daemon", "stop") == 0
    assert capsys.readouterr().out == "daemon stopped (pid 4321)\n"


def test_daemon_stop_with_nothing_running_is_an_error(run, capsys):
    assert run("daemon", "stop") == 1
    assert capsys.readouterr().err == "alarm: no daemon is running\n"


def test_a_daemon_that_will_not_stop_is_reported(run, monkeypatch, capsys):
    def wedged(root):
        raise daemon.DaemonError("daemon (pid 4321) did not stop within 10s")

    monkeypatch.setattr(daemon, "stop", wedged)
    assert run("daemon", "stop") == 1
    assert "did not stop" in capsys.readouterr().err


def test_bare_daemon_prints_its_own_help(run, capsys):
    assert run("daemon") == 2
    assert "usage: alarm daemon" in capsys.readouterr().err


# --- FR-11: the no-daemon warning ------------------------------------------


def test_add_warns_when_no_daemon_is_running(run, capsys):
    assert run("add", "07:00") == 0  # a warning, never a failure
    captured = capsys.readouterr()
    assert "alarm 1 set" in captured.out
    assert "no daemon is running" in captured.err
    assert "alarm daemon start" in captured.err  # says what to do about it


def test_cancel_warns_when_no_daemon_is_running(run, capsys):
    run("add", "07:00")
    capsys.readouterr()

    assert run("cancel", "1") == 0
    assert "no daemon is running" in capsys.readouterr().err


def test_no_warning_when_a_daemon_is_running(run, tmp_path, capsys):
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text(f"{os.getpid()}\n", encoding="utf-8")

    assert run("add", "07:00") == 0
    assert capsys.readouterr().err == ""


def test_a_stale_pid_file_does_not_silence_the_warning(run, tmp_path, monkeypatch, capsys):
    # A PID file in $HOME outlives a reboot; trusting it would make the
    # warning lie in the reassuring direction.
    paths.ensure_root(tmp_path)
    paths.pid_file(tmp_path).write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)

    run("add", "07:00")
    assert "no daemon is running" in capsys.readouterr().err


def test_list_does_not_warn(run, capsys):
    # FR-11 is about commands that *modify* alarms; `list` changes nothing.
    run("list")
    assert capsys.readouterr().err == ""


# --- the help, which is the only documentation a user is guaranteed to read --


def test_the_top_level_help_says_alarms_need_a_daemon(run, capsys):
    # DR-2: nothing starts the daemon for you, and a user who does not learn
    # that from --help learns it from an alarm that never rang.
    with pytest.raises(SystemExit) as exc:
        run("--help")
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "alarm daemon start" in out
    assert "~/.alarm-cli/" in out
    assert paths.ROOT_ENV_VAR in out


@pytest.mark.parametrize("command", ["add", "list", "cancel", "daemon"])
def test_every_command_has_help_of_its_own(run, capsys, command):
    with pytest.raises(SystemExit) as exc:
        run(command, "--help")
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert f"usage: alarm {command}" in out
    # A description, not just a usage line and a list of flags.
    assert len(out.splitlines()) > 5
