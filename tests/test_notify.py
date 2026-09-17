"""M4: ringing — command choice, and degradation when it cannot happen.

Nothing here plays audio or raises a notification: every test substitutes an
`Environment` and asserts on the command that *would* have run.
"""

import logging
import subprocess
import wave

import pytest

from alarm_cli import notify, paths
from alarm_cli.notify import Environment


class Recorder:
    """Stands in for `subprocess.run`, remembering what it was asked to do."""

    def __init__(self, returncode=0, raises=None, stderr=b""):
        self.commands = []
        self.kwargs = []
        self.returncode = returncode
        self.raises = raises
        self.stderr = stderr

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.kwargs.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(command, self.returncode, b"", self.stderr)


def environment(*available, run=None):
    """An environment in which exactly `available` binaries exist."""
    present = set(available)
    return Environment(
        which=lambda name: f"/usr/bin/{name}" if name in present else None,
        run=run if run is not None else Recorder(),
    )


LINUX = ("paplay", "notify-send")
MACOS = ("afplay", "osascript")


# --- the commands chosen ---------------------------------------------------


def test_rings_through_paplay_and_notify_send_on_linux(tmp_path):
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment(*LINUX, run=runner))

    assert runner.commands == [
        ["paplay", str(paths.wav_file(tmp_path))],
        ["notify-send", "-u", "critical", "Alarm", "standup"],
    ]


def test_rings_through_afplay_and_osascript_on_macos(tmp_path):
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment(*MACOS, run=runner))

    assert runner.commands == [
        ["afplay", str(paths.wav_file(tmp_path))],
        [
            "osascript",
            "-e",
            'display notification "standup" with title "Alarm"',
        ],
    ]


def test_falls_back_to_aplay_when_paplay_is_absent(tmp_path):
    runner = Recorder()
    notify.play_tone(tmp_path, env=environment("aplay", "afplay", run=runner))
    assert runner.commands[0][0] == "aplay"


def test_prefers_paplay_over_aplay(tmp_path):
    runner = Recorder()
    notify.play_tone(tmp_path, env=environment("paplay", "aplay", "afplay", run=runner))
    assert runner.commands[0][0] == "paplay"


def test_prefers_notify_send_over_osascript():
    runner = Recorder()
    notify.show_notification("standup", env=environment("notify-send", "osascript", run=runner))
    assert runner.commands[0][0] == "notify-send"


def test_an_alarm_with_no_message_still_says_something():
    runner = Recorder()
    notify.show_notification(None, env=environment("notify-send", run=runner))
    assert runner.commands[0][-1] == notify.DEFAULT_BODY


def test_an_empty_message_is_treated_as_no_message():
    runner = Recorder()
    notify.show_notification("", env=environment("notify-send", run=runner))
    assert runner.commands[0][-1] == notify.DEFAULT_BODY


def test_quotes_in_a_message_are_escaped_for_applescript():
    runner = Recorder()
    notify.show_notification('say "hi" \\ bye', env=environment("osascript", run=runner))
    assert runner.commands[0][2] == (
        'display notification "say \\"hi\\" \\\\ bye" with title "Alarm"'
    )


def test_a_message_is_never_passed_through_a_shell():
    # It is user input; `;` and `$(...)` in it must stay literal text.
    runner = Recorder()
    notify.show_notification("pay $(whoami); rm -rf /", env=environment("notify-send", run=runner))
    assert runner.commands[0][-1] == "pay $(whoami); rm -rf /"
    assert runner.kwargs[0].get("shell") in (None, False)


def test_every_call_is_bounded_by_a_timeout(tmp_path):
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment(*LINUX, run=runner))
    assert [kwargs["timeout"] for kwargs in runner.kwargs] == [
        notify.TIMEOUT_SECONDS,
        notify.TIMEOUT_SECONDS,
    ]


def test_output_is_captured_rather_than_left_to_the_daemon_log(tmp_path):
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment(*LINUX, run=runner))
    assert all(kwargs["capture_output"] for kwargs in runner.kwargs)


# --- degradation -----------------------------------------------------------


def test_a_bare_machine_rings_nothing_and_raises_nothing(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        notify.ring("standup", tmp_path, env=environment())

    assert "no sound player found" in caplog.text
    assert "no desktop notifier found" in caplog.text


def test_a_silent_machine_still_raises_the_notification(tmp_path):
    # The two halves are independent: no speaker must not cost you the popup.
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment("notify-send", run=runner))
    assert [command[0] for command in runner.commands] == ["notify-send"]


def test_a_missing_notifier_still_plays_the_tone(tmp_path):
    runner = Recorder()
    notify.ring("standup", tmp_path, env=environment("paplay", run=runner))
    assert [command[0] for command in runner.commands] == ["paplay"]


def test_a_binary_that_vanished_between_lookup_and_run_is_logged(tmp_path, caplog):
    runner = Recorder(raises=FileNotFoundError("paplay"))
    with caplog.at_level(logging.WARNING):
        assert notify.play_tone(tmp_path, env=environment("paplay", run=runner)) is False
    assert "not there any more" in caplog.text


def test_a_non_zero_exit_is_logged_with_its_stderr(tmp_path, caplog):
    runner = Recorder(returncode=1, stderr=b"connection refused")
    with caplog.at_level(logging.WARNING):
        assert notify.play_tone(tmp_path, env=environment("paplay", run=runner)) is False
    assert "exited 1" in caplog.text
    assert "connection refused" in caplog.text


def test_a_timeout_is_logged(tmp_path, caplog):
    runner = Recorder(raises=subprocess.TimeoutExpired("paplay", notify.TIMEOUT_SECONDS))
    with caplog.at_level(logging.WARNING):
        assert notify.play_tone(tmp_path, env=environment("paplay", run=runner)) is False
    assert "did not finish" in caplog.text


def test_an_os_error_is_logged(tmp_path, caplog):
    runner = Recorder(raises=OSError("exec format error"))
    with caplog.at_level(logging.WARNING):
        assert notify.play_tone(tmp_path, env=environment("paplay", run=runner)) is False
    assert "exec format error" in caplog.text


def test_a_failure_to_generate_the_tone_does_not_stop_the_notification(tmp_path, caplog):
    # The store root is a file, so the tone cannot be written beside it.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    runner = Recorder()
    with caplog.at_level(logging.ERROR):
        notify.ring("standup", blocked, env=environment(*LINUX, run=runner))

    assert "could not play the alarm tone" in caplog.text
    assert [command[0] for command in runner.commands] == ["notify-send"]


def test_ring_returns_nothing_and_never_raises(tmp_path):
    # The wake loop calls this; an exception here would cost every later alarm.
    assert notify.ring("standup", tmp_path, env=environment()) is None


# --- the generated tone ----------------------------------------------------


def test_the_tone_is_generated_on_first_use(tmp_path):
    tone = paths.wav_file(tmp_path)
    assert not tone.exists()

    notify.play_tone(tmp_path, env=environment("paplay"))
    assert tone.is_file()


def test_the_generated_tone_is_a_playable_wav(tmp_path):
    notify.ensure_tone(tmp_path)

    with wave.open(str(paths.wav_file(tmp_path)), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == notify.SAMPLE_WIDTH
        assert handle.getframerate() == notify.SAMPLE_RATE
        assert handle.getnframes() == int(notify.SAMPLE_RATE * notify.TONE_SECONDS)
        frames = handle.readframes(handle.getnframes())
    assert len(frames) == handle.getnframes() * notify.SAMPLE_WIDTH


def test_the_tone_starts_and_ends_quietly(tmp_path):
    # A hard edge on a sine is a click; the ramp is what prevents it.
    import array

    notify.ensure_tone(tmp_path)
    with wave.open(str(paths.wav_file(tmp_path)), "rb") as handle:
        samples = array.array("h", handle.readframes(handle.getnframes()))

    assert samples[0] == 0
    assert abs(samples[-1]) < 32767 * notify.TONE_AMPLITUDE
    assert max(abs(sample) for sample in samples) > 0


def test_an_existing_tone_is_never_regenerated(tmp_path):
    # Replacing alarm.wav is the one supported way to change the sound (TD-3).
    paths.ensure_root(tmp_path)
    tone = paths.wav_file(tmp_path)
    tone.write_bytes(b"the user's own wav")

    notify.ensure_tone(tmp_path)
    assert tone.read_bytes() == b"the user's own wav"


def test_generating_the_tone_leaves_no_temp_file_behind(tmp_path):
    notify.ensure_tone(tmp_path)
    assert [path.name for path in tmp_path.iterdir()] == ["alarm.wav"]


def test_ensure_tone_creates_the_root_directory(tmp_path):
    root = tmp_path / "not-yet"
    assert notify.ensure_tone(root).is_file()


def test_the_default_environment_reaches_the_real_world():
    assert notify.DEFAULT_ENVIRONMENT.run is subprocess.run
    assert notify.DEFAULT_ENVIRONMENT.which("sh")  # a binary every POSIX box has
