"""M1: persistence — locking, atomic replace, id allocation, refusal.

Every test points the store at ``tmp_path``; nothing here can see a real
``~/.alarm-cli``. Every time is a literal.
"""

import fcntl
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from alarm_cli import paths, store
from alarm_cli.model import Alarm, AlarmState

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 16, 22, 48, 11, tzinfo=IST)
FIRE_AT = datetime(2026, 9, 17, 7, 0, tzinfo=IST)


def add(target: store.AlarmStore, *, hour: int = 7, message: str | None = None) -> Alarm:
    return target.add(
        fire_at=FIRE_AT.replace(hour=hour),
        created_at=NOW,
        message=message,
    )


def write_raw(root, payload) -> None:
    root.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    paths.alarms_json(root).write_text(text, encoding="utf-8")


# --- absent, empty and fresh stores ---------------------------------------


def test_an_absent_store_reads_as_empty(tmp_path):
    loaded = store.load(tmp_path)
    assert loaded.next_id == 1
    assert loaded.alarms == []


def test_reading_an_absent_store_does_not_create_it(tmp_path):
    store.load(tmp_path)
    assert not paths.alarms_json(tmp_path).exists()


def test_an_empty_file_reads_as_empty(tmp_path):
    write_raw(tmp_path, "")
    assert store.load(tmp_path).alarms == []


def test_a_whitespace_only_file_reads_as_empty(tmp_path):
    write_raw(tmp_path, "\n  \n")
    assert store.load(tmp_path).alarms == []


# --- round-tripping --------------------------------------------------------


def test_round_trips_through_the_file(tmp_path):
    saved = store.AlarmStore()
    first = add(saved, hour=7, message="standup")
    second = add(saved, hour=9)
    store.save(saved, tmp_path)

    loaded = store.load(tmp_path)
    assert loaded.next_id == saved.next_id
    assert loaded.alarms == [first, second]


def test_writes_the_documented_json_shape(tmp_path):
    saved = store.AlarmStore()
    add(saved, message="standup")
    store.save(saved, tmp_path)

    raw = json.loads(paths.alarms_json(tmp_path).read_text(encoding="utf-8"))
    assert raw == {
        "schema_version": 1,
        "next_id": 2,
        "alarms": [
            {
                "id": 1,
                "message": "standup",
                "fire_at": "2026-09-17T07:00:00+05:30",
                "created_at": "2026-09-16T22:48:11+05:30",
                "state": "armed",
                "resolved_at": None,
            }
        ],
    }


def test_the_file_stays_hand_editable(tmp_path):
    saved = store.AlarmStore()
    add(saved)
    store.save(saved, tmp_path)

    text = paths.alarms_json(tmp_path).read_text(encoding="utf-8")
    assert '\n  "next_id": 2' in text  # pretty-printed, 2-space indent
    assert text.endswith("\n")


def test_saving_creates_the_root_directory(tmp_path):
    root = tmp_path / "does-not-exist-yet"
    store.save(store.AlarmStore(), root)
    assert paths.alarms_json(root).is_file()


# --- id allocation ---------------------------------------------------------


def test_ids_are_allocated_in_order(tmp_path):
    target = store.AlarmStore()
    assert [add(target).id, add(target).id, add(target).id] == [1, 2, 3]
    assert target.next_id == 4


def test_ids_are_not_reused_after_cancellation(tmp_path):
    with store.transaction(tmp_path) as target:
        first = add(target)
        add(target)

    with store.transaction(tmp_path) as target:
        target.update(first.resolve(AlarmState.CANCELLED, NOW))

    with store.transaction(tmp_path) as target:
        third = add(target)

    assert third.id == 3
    assert [alarm.id for alarm in store.load(tmp_path).alarms] == [1, 2, 3]


def test_ids_survive_a_reload(tmp_path):
    with store.transaction(tmp_path) as target:
        add(target)
    with store.transaction(tmp_path) as target:
        assert add(target).id == 2


def test_get_and_armed_select_by_id_and_state(tmp_path):
    target = store.AlarmStore()
    first = add(target)
    second = add(target, hour=9)
    target.update(first.resolve(AlarmState.FIRED, NOW))

    assert target.get(second.id) == second
    assert target.get(404) is None
    assert target.armed() == [second]


def test_updating_an_unknown_alarm_is_a_bug_not_a_user_error(tmp_path):
    target = store.AlarmStore()
    stray = Alarm(id=99, message=None, fire_at=FIRE_AT, created_at=NOW)
    with pytest.raises(KeyError):
        target.update(stray)


# --- transactions ----------------------------------------------------------


def test_a_transaction_persists_its_changes(tmp_path):
    with store.transaction(tmp_path) as target:
        add(target, message="standup")

    assert store.load(tmp_path).alarms[0].message == "standup"


def test_a_transaction_that_changes_nothing_does_not_write(tmp_path):
    with store.transaction(tmp_path) as target:
        add(target)
    before = paths.alarms_json(tmp_path).stat().st_mtime_ns

    # The daemon sweeps every minute and usually finds nothing to do (NFR-4).
    with store.transaction(tmp_path) as target:
        assert target.armed()

    assert paths.alarms_json(tmp_path).stat().st_mtime_ns == before


def test_a_failing_transaction_writes_nothing(tmp_path):
    with store.transaction(tmp_path) as target:
        add(target)
    before = paths.alarms_json(tmp_path).read_text(encoding="utf-8")

    with pytest.raises(RuntimeError):
        with store.transaction(tmp_path) as target:
            add(target, hour=9)
            raise RuntimeError("boom")

    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == before


def test_the_lock_file_is_created_beside_the_store(tmp_path):
    store.load(tmp_path)
    assert paths.lock_file(tmp_path).exists()


def test_a_transaction_holds_the_lock_for_its_whole_body(tmp_path):
    # Probed non-blockingly: a second writer would *wait* here, and a test that
    # waits is a test that hangs when the locking is wrong.
    store.load(tmp_path)
    fd = os.open(paths.lock_file(tmp_path), os.O_RDWR)
    try:
        with store.transaction(tmp_path) as target:
            add(target)
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # ...and releases it on the way out.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_readers_share_the_lock(tmp_path):
    store.load(tmp_path)
    fd = os.open(paths.lock_file(tmp_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        # `alarm list` must not queue behind another `alarm list`.
        assert store.load(tmp_path).alarms == []
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --- durability ------------------------------------------------------------


def test_a_crash_between_write_and_replace_leaves_the_old_store_intact(tmp_path, monkeypatch):
    with store.transaction(tmp_path) as target:
        add(target, message="survivor")
    before = paths.alarms_json(tmp_path).read_text(encoding="utf-8")

    def crash(src, dst):
        raise OSError("power cut")

    monkeypatch.setattr(store.os, "replace", crash)
    with pytest.raises(OSError):
        with store.transaction(tmp_path) as target:
            add(target, hour=9, message="lost")

    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == before
    assert store.load(tmp_path).alarms[0].message == "survivor"


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    store.save(store.AlarmStore(), tmp_path)

    monkeypatch.setattr(store.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        store.save(store.AlarmStore(), tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["alarms.json", "alarms.lock"]


def test_the_store_is_replaced_not_rewritten_in_place(tmp_path):
    # An in-place rewrite is the thing that can be observed half-written.
    store.save(store.AlarmStore(), tmp_path)
    first_inode = paths.alarms_json(tmp_path).stat().st_ino

    saved = store.AlarmStore()
    add(saved)
    store.save(saved, tmp_path)

    assert paths.alarms_json(tmp_path).stat().st_ino != first_inode


# --- refusals --------------------------------------------------------------


def test_malformed_json_is_refused_and_the_file_is_left_alone(tmp_path):
    write_raw(tmp_path, "{not json at all")

    with pytest.raises(store.StoreError) as exc:
        store.load(tmp_path)

    message = str(exc.value)
    assert str(paths.alarms_json(tmp_path)) in message  # tells the user where
    assert "will not overwrite" in message
    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == "{not json at all"


def test_a_newer_schema_version_is_refused_rather_than_guessed_at(tmp_path):
    write_raw(tmp_path, {"schema_version": 2, "next_id": 1, "alarms": []})

    with pytest.raises(store.StoreError, match="schema_version 2"):
        store.load(tmp_path)


def test_an_unrecognised_schema_version_is_refused(tmp_path):
    write_raw(tmp_path, {"schema_version": "one", "next_id": 1, "alarms": []})

    with pytest.raises(store.StoreError, match="unrecognised schema_version"):
        store.load(tmp_path)


def test_a_transaction_over_a_corrupt_store_refuses_before_the_body_runs(tmp_path):
    write_raw(tmp_path, "{not json at all")

    with pytest.raises(store.StoreError):
        with store.transaction(tmp_path) as target:  # pragma: no cover - never entered
            add(target)

    assert paths.alarms_json(tmp_path).read_text(encoding="utf-8") == "{not json at all"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "should hold a JSON object"),
        ({"schema_version": 1, "alarms": []}, "next_id must be a positive integer"),
        ({"schema_version": 1, "next_id": 0, "alarms": []}, "next_id must be a positive integer"),
        ({"schema_version": 1, "next_id": "3", "alarms": []}, "next_id must be a positive integer"),
        ({"schema_version": 1, "next_id": 1, "alarms": {}}, "alarms must be a list"),
    ],
)
def test_a_structurally_broken_store_is_refused(tmp_path, payload, message):
    write_raw(tmp_path, payload)
    with pytest.raises(store.StoreError, match=message):
        store.load(tmp_path)


def test_an_unreadable_alarm_record_names_the_file_and_the_reason(tmp_path):
    write_raw(
        tmp_path,
        {
            "schema_version": 1,
            "next_id": 2,
            "alarms": [
                {
                    "id": 1,
                    "message": None,
                    "fire_at": "not a date",
                    "created_at": "2026-09-16T22:48:11+05:30",
                    "state": "armed",
                    "resolved_at": None,
                }
            ],
        },
    )

    with pytest.raises(store.StoreError) as exc:
        store.load(tmp_path)

    assert str(paths.alarms_json(tmp_path)) in str(exc.value)
    assert "fire_at" in str(exc.value)


def test_duplicate_ids_are_refused(tmp_path):
    record = {
        "id": 1,
        "message": None,
        "fire_at": "2026-09-17T07:00:00+05:30",
        "created_at": "2026-09-16T22:48:11+05:30",
        "state": "armed",
        "resolved_at": None,
    }
    write_raw(tmp_path, {"schema_version": 1, "next_id": 2, "alarms": [record, dict(record)]})

    with pytest.raises(store.StoreError, match="share an id"):
        store.load(tmp_path)


def test_a_next_id_that_would_reuse_an_id_is_refused(tmp_path):
    # Easy to produce by hand-editing; it would hand two alarms the same id.
    write_raw(
        tmp_path,
        {
            "schema_version": 1,
            "next_id": 1,
            "alarms": [
                {
                    "id": 1,
                    "message": None,
                    "fire_at": "2026-09-17T07:00:00+05:30",
                    "created_at": "2026-09-16T22:48:11+05:30",
                    "state": "armed",
                    "resolved_at": None,
                }
            ],
        },
    )

    with pytest.raises(store.StoreError, match="ids would be reused"):
        store.load(tmp_path)


# --- the default root ------------------------------------------------------


def test_the_default_root_is_used_when_none_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    with store.transaction() as target:
        add(target, message="via the environment")

    assert store.load(tmp_path).alarms[0].message == "via the environment"
    assert os.path.exists(paths.alarms_json(tmp_path))
