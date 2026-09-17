"""Sound and desktop notification, with degradation.

Never raises into its caller: a missing player, a non-zero exit and a timeout
each degrade to a log line, because an alarm that cannot be made audible has
still happened. The daemon marks the alarm `fired` either way (TD-4).

Everything this module reaches for outside the process — looking up a binary,
running it — arrives in an :class:`Environment`, so tests assert on the command
that *would* have run and nothing plays audio in CI.
"""

from __future__ import annotations

import array
import logging
import math
import os
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from alarm_cli import paths

#: The daemon points the root logger at `daemon.log` (M5). Until it does, these
#: lines go wherever the process's logging is configured — in a test, at the
#: `caplog` fixture.
log = logging.getLogger(__name__)

#: Sound players, in the order they are tried. `paplay` and `aplay` are Linux,
#: `afplay` is macOS; no platform check is needed because a machine only has
#: the ones it has.
PLAYERS = ("paplay", "aplay", "afplay")

#: Desktop notifiers, in the order they are tried.
NOTIFIERS = ("notify-send", "osascript")

#: Long enough for a player to start on a loaded machine, short enough that a
#: hung binary cannot delay the next wake by a whole minute.
TIMEOUT_SECONDS = 10.0

#: What the notification says when the alarm carries no message.
DEFAULT_BODY = "Time's up"

NOTIFICATION_TITLE = "Alarm"

# The generated tone: a 1.2-second A5 sine, which is audible on a laptop
# speaker without being shrill, and short enough not to overlap the next wake.
TONE_HZ = 880
TONE_SECONDS = 1.2
SAMPLE_RATE = 44_100
SAMPLE_WIDTH = 2  # bytes; 16-bit signed
TONE_AMPLITUDE = 0.35  # of full scale, leaving headroom
FADE_SECONDS = 0.01  # a ramp at each end; a hard start or stop clicks


@dataclass(frozen=True)
class Environment:
    """The outside world, as two callables.

    ``which`` decides which binaries exist; ``run`` runs one. Tests pass fakes
    and assert on what would have been run.
    """

    which: Callable[[str], str | None] = field(default=shutil.which)
    run: Callable[..., subprocess.CompletedProcess] = field(default=subprocess.run)


DEFAULT_ENVIRONMENT = Environment()


def ring(
    message: str | None = None,
    root: Path | str | None = None,
    *,
    env: Environment = DEFAULT_ENVIRONMENT,
) -> None:
    """Make as much noise as this machine allows. Never raises.

    The sound and the notification are independent: whichever one works,
    works. The caller is the wake loop, and an exception here would stop
    alarms it has not reached yet from ringing at all.
    """
    try:
        play_tone(root, env=env)
    except Exception:  # noqa: BLE001 - a ring must not take the daemon down
        log.exception("could not play the alarm tone")

    try:
        show_notification(message, env=env)
    except Exception:  # noqa: BLE001 - likewise
        log.exception("could not raise the desktop notification")


def play_tone(root: Path | str | None = None, *, env: Environment = DEFAULT_ENVIRONMENT) -> bool:
    """Play `alarm.wav`, generating it first if it is not there yet."""
    player = _first_available(PLAYERS, env)
    if player is None:
        log.warning(
            "no sound player found (tried %s); the alarm is silent", ", ".join(PLAYERS)
        )
        return False

    tone = ensure_tone(root)
    return _run([player, str(tone)], env)


def show_notification(
    message: str | None = None, *, env: Environment = DEFAULT_ENVIRONMENT
) -> bool:
    """Raise a desktop notification carrying the alarm's message."""
    notifier = _first_available(NOTIFIERS, env)
    if notifier is None:
        log.warning(
            "no desktop notifier found (tried %s); the alarm is invisible",
            ", ".join(NOTIFIERS),
        )
        return False

    body = message or DEFAULT_BODY
    return _run(_notification_command(notifier, body), env)


def _notification_command(notifier: str, body: str) -> list[str]:
    if notifier == "notify-send":
        # -u critical so the notification stays up rather than fading after a
        # few seconds; an alarm nobody was looking at is an alarm missed.
        return ["notify-send", "-u", "critical", NOTIFICATION_TITLE, body]
    return [
        "osascript",
        "-e",
        f'display notification "{_applescript(body)}" '
        f'with title "{_applescript(NOTIFICATION_TITLE)}"',
    ]


def _applescript(text: str) -> str:
    """Escape for an AppleScript string literal.

    The command is passed as an argv list, so the shell is not involved — only
    AppleScript's own quoting is.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _first_available(candidates: tuple[str, ...], env: Environment) -> str | None:
    for candidate in candidates:
        if env.which(candidate):
            return candidate
    return None


def _run(command: list[str], env: Environment) -> bool:
    """Run one best-effort command. Every failure is a log line, not an exception."""
    try:
        result = env.run(
            command,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        # `which` said it was there; between then and now it was not.
        log.warning("%s is not there any more", command[0])
        return False
    except subprocess.TimeoutExpired:
        log.warning("%s did not finish within %ss", command[0], TIMEOUT_SECONDS)
        return False
    except OSError as exc:
        log.warning("could not run %s: %s", command[0], exc)
        return False

    if result.returncode != 0:
        log.warning(
            "%s exited %s: %s",
            command[0],
            result.returncode,
            _stderr(result),
        )
        return False

    log.info("ran %s", " ".join(command))
    return True


def _stderr(result: subprocess.CompletedProcess) -> str:
    err = result.stderr
    if not err:
        return "no stderr"
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return err.strip()


# --- the tone --------------------------------------------------------------


def ensure_tone(root: Path | str | None = None) -> Path:
    """Return the path to `alarm.wav`, generating it if it is absent.

    Generated rather than shipped so the repository carries no binary asset
    (NFR-2, DR-6). Replaced by the user at any time — if the file is there,
    whatever it contains is what rings.
    """
    tone = paths.wav_file(root)
    if tone.exists():
        return tone

    paths.ensure_root(root)
    _write_tone(tone)
    log.info("generated the alarm tone at %s", tone)
    return tone


def _write_tone(tone: Path) -> None:
    """Write a fading sine to `tone`, atomically.

    Atomically because a half-written WAV is worse than no WAV: it would exist,
    so it would never be regenerated, and every alarm after it would be silent.
    """
    fd, tmp_name = tempfile.mkstemp(dir=tone.parent, prefix=".alarm-", suffix=".wav")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with wave.open(str(tmp), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(_samples().tobytes())
        os.replace(tmp, tone)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _samples() -> array.array:
    total = int(SAMPLE_RATE * TONE_SECONDS)
    fade = max(1, int(SAMPLE_RATE * FADE_SECONDS))
    peak = int(TONE_AMPLITUDE * 32767)
    step = 2 * math.pi * TONE_HZ / SAMPLE_RATE

    samples = array.array("h", bytes(total * SAMPLE_WIDTH))
    for index in range(total):
        # Linear ramp in and out, so the tone does not start or stop on a
        # discontinuity — that is what makes a click.
        envelope = min(1.0, index / fade, (total - index) / fade)
        samples[index] = int(peak * envelope * math.sin(step * index))
    return samples
