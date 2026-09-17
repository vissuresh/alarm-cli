"""Every path under ``~/.alarm-cli/``, and nothing else.

Owns the five files listed in the README: ``alarms.json``, ``alarms.lock``,
``daemon.pid``, ``daemon.log`` and ``alarm.wav``.

Every accessor takes an optional root so that tests can point the whole tree at
``tmp_path`` (NFR-6). ``ALARM_CLI_HOME`` overrides the default root for callers
that cannot pass one — notably the M5 integration test, which drives a real
detached daemon through the console script and has no argument to hand it.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment override for the root, for callers reached through a process
#: boundary rather than a function call.
ROOT_ENV_VAR = "ALARM_CLI_HOME"

DEFAULT_ROOT_NAME = ".alarm-cli"

ALARMS_NAME = "alarms.json"
LOCK_NAME = "alarms.lock"
PID_NAME = "daemon.pid"
LOG_NAME = "daemon.log"
WAV_NAME = "alarm.wav"


def default_root() -> Path:
    """The root directory, from ``ALARM_CLI_HOME`` or ``~/.alarm-cli``.

    The environment is read on every call rather than at import, so that a test
    or a shell can change it without reloading the module.
    """
    override = os.environ.get(ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_ROOT_NAME


def _resolve(root: Path | str | None) -> Path:
    return default_root() if root is None else Path(root)


def alarms_json(root: Path | str | None = None) -> Path:
    """The store itself: one JSON document, hand-editable."""
    return _resolve(root) / ALARMS_NAME


def lock_file(root: Path | str | None = None) -> Path:
    """The ``flock`` target.

    Deliberately a different file from ``alarms.json``: the store is replaced by
    rename on every write, and a lock held on a replaced file protects nothing.
    """
    return _resolve(root) / LOCK_NAME


def pid_file(root: Path | str | None = None) -> Path:
    return _resolve(root) / PID_NAME


def log_file(root: Path | str | None = None) -> Path:
    return _resolve(root) / LOG_NAME


def wav_file(root: Path | str | None = None) -> Path:
    """The tone. Generated on first use (M4); replaceable by the user."""
    return _resolve(root) / WAV_NAME


def ensure_root(root: Path | str | None = None) -> Path:
    """Create the root directory if it is absent and return it."""
    resolved = _resolve(root)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
