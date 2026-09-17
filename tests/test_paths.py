"""M1: the path layout, and the override that keeps tests out of a real home."""

from pathlib import Path

from alarm_cli import paths


def test_every_file_lives_under_the_given_root(tmp_path):
    assert paths.alarms_json(tmp_path) == tmp_path / "alarms.json"
    assert paths.lock_file(tmp_path) == tmp_path / "alarms.lock"
    assert paths.pid_file(tmp_path) == tmp_path / "daemon.pid"
    assert paths.log_file(tmp_path) == tmp_path / "daemon.log"
    assert paths.wav_file(tmp_path) == tmp_path / "alarm.wav"


def test_the_lock_is_not_the_store(tmp_path):
    # The store is replaced by rename on every write; a lock held on it would
    # be dropped with the old inode.
    assert paths.lock_file(tmp_path) != paths.alarms_json(tmp_path)


def test_default_root_is_a_dotfile_directory_in_home(monkeypatch):
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    assert paths.default_root() == Path.home() / ".alarm-cli"


def test_environment_overrides_the_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    assert paths.default_root() == tmp_path
    assert paths.alarms_json() == tmp_path / "alarms.json"


def test_environment_override_expands_a_tilde(monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, "~/somewhere")
    assert paths.default_root() == Path.home() / "somewhere"


def test_empty_override_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, "")
    assert paths.default_root() == Path.home() / ".alarm-cli"


def test_ensure_root_creates_the_directory(tmp_path):
    root = tmp_path / "nested" / "root"
    assert paths.ensure_root(root) == root
    assert root.is_dir()
    # Idempotent: a second call on an existing directory is not an error.
    assert paths.ensure_root(root) == root
