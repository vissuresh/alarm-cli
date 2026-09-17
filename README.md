# alarm-cli

A dependency-free, terminal-only alarm clock for POSIX systems.

Set an alarm for a clock time, get on with your work, and be interrupted by a
sound and a desktop notification when the time comes. No database, no GUI, no
third-party packages.

> **Status: in progress.** Everything described below works. What is left is
> release polish — see [docs/project_status.md](docs/project_status.md). See
> [docs/project_status.md](docs/project_status.md) for what exists today and
> [PLAN.md](PLAN.md) for the build order.

## How it works

`alarm-cli` is split in two halves:

- a **client** — the `alarm` command you type, which reads and writes a JSON file
- a **daemon** — a background process you start once, which watches that file and
  rings alarms when they come due

The client never rings anything, and the daemon never talks to your terminal.
They communicate only through `~/.alarm-cli/alarms.json`.

This means **an alarm only rings while the daemon is running.** Alarms are not
lost if the daemon is down, but they will not ring late either — see
[Missed alarms](#missed-alarms).

## Requirements

- Python 3.12 or newer
- Linux or macOS (POSIX)
- Optional, for a better ring: `paplay`/`aplay` (Linux) or `afplay` (macOS) for
  sound, and `notify-send` (Linux) or `osascript` (macOS) for desktop
  notifications. Anything missing is skipped; the alarm still fires and is
  logged.

## Install

_Not yet packaged._ Once the scaffolding lands, installation will be:

```sh
uv tool install .      # or: pip install --user .
```

## Usage

Start the daemon once per login session:

```sh
alarm daemon start
```

Set an alarm for the **next** occurrence of a clock time — today if that time is
still ahead, tomorrow otherwise:

```sh
alarm add 07:00 -m "standup"
alarm add 14:30
```

Times are 24-hour and zero-padded — `07:00`, not `7:00` or `7am`. Anything else
is refused rather than guessed at.

See what is armed, soonest first:

```sh
alarm list
```

```
ID  FIRES AT          IN      MESSAGE
2   2026-09-16 23:30  42m     tea
1   2026-09-17 07:00  8h 12m  standup
```

`alarm list --all` adds the alarms that already fired, were missed, or were
cancelled, with the time each one reached that state:

```
ID  FIRES AT          IN      MESSAGE
2   2026-09-16 23:30  42m     tea
1   2026-09-17 07:00  8h 12m  standup

ID  FIRES AT          STATE   RESOLVED AT       MESSAGE
4   2026-09-16 18:00  fired   2026-09-16 18:00  walk
3   2026-09-16 14:30  missed  2026-09-16 18:20  -
```

Cancel one, or check on the daemon:

```sh
alarm cancel 1
alarm daemon status
alarm daemon stop
```

Ids are never reused, so a cancelled id in your shell history can never later
hit a different alarm.

## Missed alarms

If the daemon is not running when an alarm comes due, that alarm is marked
`missed` and **will never ring** — a 07:00 alarm should not blare at 11:00. The
same applies after the machine resumes from suspend: anything more than a short
grace period overdue is recorded as missed rather than fired.

`alarm list --all` shows missed alarms so you can see what you didn't hear.

## Where things live

Everything lives in one directory, `~/.alarm-cli/`:

| File | Purpose |
| --- | --- |
| `alarms.json` | every alarm and its state |
| `alarms.lock` | guards concurrent read-modify-write |
| `daemon.pid` | the running daemon's PID |
| `daemon.log` | what the daemon did and when |
| `alarm.wav` | the ring tone (generated on first run; replace it with your own) |

Set `ALARM_CLI_HOME` to keep that directory somewhere else. It applies to the
client and the daemon alike, so export it before `alarm daemon start` or the two
halves will read different files.

## What it deliberately does not do

No recurring alarms, no countdown timers, no snooze, no reboot persistence, no
config file, no Windows support. These are scope decisions, not oversights — the
reasoning is in [project_spec.md](project_spec.md#known-limitations).

## Documentation

- [project_spec.md](project_spec.md) — requirements, JSON schema, command specs
- [docs/architecture.md](docs/architecture.md) — system design, data and user flow
- [PLAN.md](PLAN.md) — MVP build plan
- [docs/changelog.md](docs/changelog.md) — version history and decision records
- [docs/project_status.md](docs/project_status.md) — current progress
- [docs/TECH_DEBT.md](docs/TECH_DEBT.md) — known debt and deferred work
