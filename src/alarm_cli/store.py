"""Load and save ``alarms.json``: locking, atomic replace, id allocation.

Knows how alarms are persisted, not what they mean. Three entry points:

``load(root)``      read under a shared lock — for ``list`` and other readers.
``save(store, root)`` write under an exclusive lock.
``transaction(root)`` read, hand the caller the store, write back what changed,
                    all under one exclusive lock — for every read-modify-write.

Use ``transaction`` for anything that changes an alarm. ``load`` then ``save``
leaves a window in which the other process can write between the two, and the
second writer wins silently. Do not call ``save`` or ``load`` inside a
``transaction``: ``flock`` is per file descriptor, so the nested acquisition
waits on a lock this process is already holding and never returns.

A store that cannot be understood is never repaired or reset — it is refused
with the path in the message, because resetting destroys alarms.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from alarm_cli import paths
from alarm_cli.model import Alarm, AlarmState

#: Bumped only when the on-disk shape changes incompatibly. A store written by
#: a newer version is refused rather than guessed at.
SCHEMA_VERSION = 1


class StoreError(Exception):
    """The store is unusable and only the user can fix it.

    Carries a message naming the file and the next move. Raised for malformed
    JSON, an unknown schema version and an unreadable alarm record — never for
    a store that is merely absent.
    """


@dataclass
class AlarmStore:
    """The whole document: an id counter and the alarms."""

    next_id: int = 1
    alarms: list[Alarm] = field(default_factory=list)

    def add(
        self,
        *,
        fire_at: datetime,
        created_at: datetime,
        message: str | None = None,
    ) -> Alarm:
        """Append a new armed alarm and allocate it the next id."""
        alarm = Alarm(
            id=self.next_id,
            message=message,
            fire_at=fire_at,
            created_at=created_at,
            state=AlarmState.ARMED,
        )
        # Ids are never reused, so a cancelled id in your shell history can
        # never later hit a different alarm.
        self.next_id += 1
        self.alarms.append(alarm)
        return alarm

    def get(self, alarm_id: int) -> Alarm | None:
        for alarm in self.alarms:
            if alarm.id == alarm_id:
                return alarm
        return None

    def armed(self) -> list[Alarm]:
        return [alarm for alarm in self.alarms if alarm.state is AlarmState.ARMED]

    def update(self, alarm: Alarm) -> None:
        """Swap in a new version of an alarm already in the store, by id."""
        for index, existing in enumerate(self.alarms):
            if existing.id == alarm.id:
                self.alarms[index] = alarm
                return
        raise KeyError(f"no alarm with id {alarm.id}")


def load(root: Path | str | None = None) -> AlarmStore:
    """Read the store under a shared lock. An absent store reads as empty."""
    with _flock(root, fcntl.LOCK_SH):
        return _read(paths.alarms_json(root))


def save(store: AlarmStore, root: Path | str | None = None) -> None:
    """Write the store under an exclusive lock, atomically."""
    with _flock(root, fcntl.LOCK_EX):
        _write(store, paths.alarms_json(root))


@contextmanager
def transaction(root: Path | str | None = None) -> Iterator[AlarmStore]:
    """Hold the exclusive lock across a read-modify-write.

    The store is written back only if the caller actually changed something, so
    the daemon's once-a-minute sweep over an unchanged store costs no write.
    If the body raises, nothing is written.
    """
    with _flock(root, fcntl.LOCK_EX):
        path = paths.alarms_json(root)
        store = _read(path)
        before = _payload(store)
        yield store
        after = _payload(store)
        if after != before:
            _write(store, path)


@contextmanager
def _flock(root: Path | str | None, operation: int) -> Iterator[None]:
    lock_path = paths.lock_file(root)
    paths.ensure_root(root)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, operation)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read(path: Path) -> AlarmStore:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AlarmStore()
    if not text.strip():
        # A zero-length file is what a store looks like the instant before its
        # first write, not corruption.
        return AlarmStore()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(
            f"{path} is not valid JSON ({exc}). "
            "alarm-cli will not overwrite it; inspect it, fix it, or delete it."
        ) from exc
    return _decode(raw, path)


def _write(store: AlarmStore, path: Path) -> None:
    """Land the store atomically: temp file in the same directory, then rename.

    A crash therefore leaves ``alarms.json`` either fully at its old value or
    fully at its new one, never half-written (FR-12).
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    # A 2-space indent keeps the file diffable and hand-editable (goal 2).
    text = json.dumps(_payload(store), indent=2) + "\n"

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".alarms-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # fsync the directory too: the bytes being durable is not the same as the
    # rename that publishes them being durable.
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _payload(store: AlarmStore) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "next_id": store.next_id,
        "alarms": [alarm.to_dict() for alarm in store.alarms],
    }


def _decode(raw: Any, path: Path) -> AlarmStore:
    if not isinstance(raw, dict):
        raise StoreError(f"{path} should hold a JSON object, not a {type(raw).__name__}.")

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
            raise StoreError(
                f"{path} has schema_version {version}, but this alarm-cli understands "
                f"{SCHEMA_VERSION}. Upgrade alarm-cli, or move the file aside."
            )
        raise StoreError(
            f"{path} has an unrecognised schema_version {version!r} "
            f"(expected {SCHEMA_VERSION})."
        )

    next_id = raw.get("next_id")
    if not isinstance(next_id, int) or isinstance(next_id, bool) or next_id < 1:
        raise StoreError(f"{path}: next_id must be a positive integer, found {next_id!r}.")

    records = raw.get("alarms")
    if not isinstance(records, list):
        raise StoreError(f"{path}: alarms must be a list.")

    alarms = []
    for record in records:
        try:
            alarms.append(Alarm.from_dict(record))
        except ValueError as exc:
            raise StoreError(f"{path}: {exc}") from exc

    seen = {alarm.id for alarm in alarms}
    if len(seen) != len(alarms):
        raise StoreError(f"{path}: two alarms share an id.")
    highest = max(seen, default=0)
    if next_id <= highest:
        raise StoreError(
            f"{path}: next_id is {next_id} but alarm {highest} already exists; "
            "ids would be reused."
        )

    return AlarmStore(next_id=next_id, alarms=alarms)
