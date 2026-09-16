# alarm-cli — Project Specification

Single source of truth for **what** alarm-cli does and **how** it is built.
System design and diagrams live in [docs/architecture.md](docs/architecture.md);
the decisions behind the design, with dates, live in
[docs/changelog.md](docs/changelog.md).

- **Version:** 0.1.0 (unreleased)
- **Status:** specified, not implemented

---

# Part 1 — Product Requirements (PRD)

## 1. Who is the product for

Developers and other terminal-resident users on Linux or macOS who already keep a
shell open all day, and who want a reminder without leaving it.

Assumptions about this user, which the design leans on:

- comfortable starting a background process and reading a log file
- wants zero install friction — no package tree, no service registration
- treats the terminal as the primary interface, not a fallback

Explicitly **not** the audience: phone users, users who need alarms to survive a
reboot unattended, Windows users, and anyone who needs a GUI.

## 2. What problem does the product solve

A focused terminal user misses time-based commitments — a meeting, a standup, a
tea that has steeped — because nothing in their working environment interrupts
them. Existing options each fail in a specific way:

| Option | Why it fails this user |
| --- | --- |
| Phone alarm | context switch out of the machine; awkward for one-off, minutes-away reminders |
| `sleep 600 && notify-send ...` | occupies a terminal, is not inspectable, and is lost the moment the shell closes |
| Calendar app | heavyweight for "remind me at 14:30 today"; needs a GUI and often an account |
| `cron` / `systemd` timers | system-level and persistent by nature; hostile to one-off, throwaway reminders |

alarm-cli fills the gap: a one-off alarm, set in one line, that survives closing
the terminal you set it in, is listable and cancellable, and interrupts you
loudly enough to notice.

## 3. What does the product do

### In scope for v1 (MVP)

- **Set a one-off alarm for a clock time.** `alarm add HH:MM` resolves to the
  *next* occurrence of that time: today if it is still ahead, otherwise
  tomorrow. An optional message is attached.
- **List alarms.** Armed alarms by default; the full history with `--all`.
- **Cancel an armed alarm** by id.
- **Ring**, when an alarm comes due and the daemon is running: play a sound and
  raise a desktop notification, then mark the alarm fired.
- **Skip missed alarms.** An alarm that came due while the daemon was stopped (or
  while the machine was suspended) is marked `missed` and never rings.
- **Manage the daemon** explicitly: `start`, `stop`, `status`.

### Out of scope for v1

Recurring alarms, countdown timers, snooze, dismissal/acknowledgement, editing an
existing alarm, reboot persistence, a config file, Windows support, multi-user or
networked operation. Each is a deliberate cut, recorded with its reasoning in
[Known limitations](#known-limitations).

## 4. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-1 | `alarm add <HH:MM> [-m MSG]` stores a new alarm whose fire time is the next occurrence of `HH:MM` in local time, and prints the resolved absolute date-time. |
| FR-2 | `add` rejects a malformed time with a non-zero exit code and a message naming the accepted format, without modifying the store. |
| FR-3 | `alarm list` prints armed alarms ordered by fire time, with id, absolute fire time, time remaining, and message. |
| FR-4 | `alarm list --all` additionally prints `fired`, `missed` and `cancelled` alarms, each with the time it reached that state. |
| FR-5 | `alarm cancel <id>` moves an armed alarm to `cancelled`. Cancelling an unknown or non-armed id exits non-zero and changes nothing. |
| FR-6 | `alarm daemon start` starts exactly one detached daemon, writes its PID, and exits non-zero if a live daemon already holds the PID file. |
| FR-7 | `alarm daemon stop` signals the running daemon to terminate and removes the PID file; `status` reports running (with PID) or not running. |
| FR-8 | While running, the daemon fires each armed alarm whose fire time has passed by no more than the grace window: it plays a sound, raises a desktop notification, writes a log line, and sets the alarm to `fired`. |
| FR-9 | An armed alarm overdue by more than the grace window is set to `missed` without ringing. This is checked on daemon start and on every wake. |
| FR-10 | Every alarm record carries a full local date-time, not a bare clock time, so missed detection survives a daemon restart on a later day. |
| FR-11 | Client commands warn on stderr, without failing, when they modify alarms while no daemon is running. |
| FR-12 | Every state change is durable: a crash mid-write must leave `alarms.json` either fully at its previous value or fully at its new one. |

## 5. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | **Dependencies:** zero runtime dependencies outside the Python standard library. `pytest` is the only development dependency. |
| NFR-2 | **Runtime:** Python 3.12+. No compiled extensions, no bundled binary assets. |
| NFR-3 | **Accuracy:** an alarm rings within one second of its fire time under normal load. |
| NFR-4 | **Footprint:** an idle daemon wakes at most once per minute and does no work beyond one store read per wake. |
| NFR-5 | **Degradation:** a missing sound player or notifier never fails an alarm — the ring degrades to a log line. |
| NFR-6 | **Testability:** no test may sleep for real time or depend on the wall clock. Time and subprocess invocation are injected at the seam. |
| NFR-7 | **Safety:** the store is never corrupted by concurrent client and daemon writes. |
| NFR-8 | **Transparency:** every daemon action — start, skipped or late wakes, ring, miss, stop — is appended to `daemon.log` with a timestamp. |

---

# Part 2 — Technical Design (EDD)

## 1. Stack and layout

Python 3.12+, standard library only: `argparse`, `json`, `datetime`, `pathlib`,
`subprocess`, `signal`, `fcntl`, `os`, `wave`, `logging`. Tests use `pytest`.

Planned package layout (not yet created):

```
src/alarm_cli/
  cli.py         argparse surface; parses, delegates, formats, sets exit codes
  store.py       load/save alarms.json, locking, atomic replace, id allocation
  model.py       Alarm dataclass, AlarmState, JSON (de)serialisation
  timeparse.py   "HH:MM" -> next occurrence as an aware datetime
  daemon.py      start/stop/status, detach, the wake loop, miss detection
  notify.py      sound and desktop notification, with degradation
  paths.py       everything under ~/.alarm-cli/
tests/
```

Dependency direction is strictly one-way: `cli` → {`store`, `daemon`,
`timeparse`} → {`model`, `paths`}, and `daemon` → {`store`, `notify`}. Nothing
imports `cli`.

## 2. JSON structure

`~/.alarm-cli/alarms.json`, UTF-8, written atomically, pretty-printed with a
2-space indent so it stays diffable and hand-editable.

```json
{
  "schema_version": 1,
  "next_id": 3,
  "alarms": [
    {
      "id": 1,
      "message": "standup",
      "fire_at": "2026-09-17T07:00:00+05:30",
      "created_at": "2026-09-16T22:48:11+05:30",
      "state": "armed",
      "resolved_at": null
    },
    {
      "id": 2,
      "message": null,
      "fire_at": "2026-09-16T14:30:00+05:30",
      "created_at": "2026-09-16T09:05:40+05:30",
      "state": "missed",
      "resolved_at": "2026-09-16T18:20:03+05:30"
    }
  ]
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | `1`. A store with a higher version is refused rather than guessed at. |
| `next_id` | int | Monotonic. Ids are never reused, so a cancelled id in your shell history can never hit a different alarm. |
| `alarms[].id` | int | Stable for the life of the store. |
| `alarms[].message` | string \| null | Free text; `null` when `-m` was omitted. |
| `alarms[].fire_at` | string | ISO 8601 **with UTC offset**, resolved at creation time (FR-10). |
| `alarms[].created_at` | string | ISO 8601 with offset. |
| `alarms[].state` | enum | `armed` \| `fired` \| `missed` \| `cancelled`. |
| `alarms[].resolved_at` | string \| null | When the alarm left `armed`; `null` while armed. |

**State machine.** `armed` is the only non-terminal state:

```
armed ──ring (due, within grace)──> fired
      ──overdue beyond grace──────> missed
      ──alarm cancel <id>─────────> cancelled
```

**Missing or empty file** is not an error: it is treated as
`{"schema_version": 1, "next_id": 1, "alarms": []}`. **Malformed JSON** is an
error — the store is left untouched and the user is told to inspect or delete the
file, because silently resetting would destroy alarms.

## 3. Available commands and flows

`alarm` is the console script. Exit codes: `0` success, `1` a handled error
(bad input, unknown id, daemon already running), `2` argparse usage error.

| Command | Reads | Writes | Behaviour |
| --- | --- | --- | --- |
| `alarm add <HH:MM> [-m MSG]` | store | store | Resolve next occurrence, append `armed` alarm, bump `next_id`, print id and resolved time. Warn if no daemon (FR-11). |
| `alarm list [--all]` | store | — | Armed alarms sorted by `fire_at`; `--all` appends terminal-state alarms sorted by `resolved_at`. |
| `alarm cancel <id>` | store | store | `armed` → `cancelled`, stamp `resolved_at`. |
| `alarm daemon start` | pid file | pid file, log | Refuse if a live daemon holds the PID file; otherwise detach and run the wake loop. |
| `alarm daemon stop` | pid file | pid file | `SIGTERM` the daemon, wait for exit, remove the PID file. |
| `alarm daemon status` | pid file | — | Print running + PID, or not running. Clears a stale PID file it finds. |

### Time resolution (`timeparse`)

Input is `HH:MM` in 24-hour form, local time zone. Given `now`:

- if today at `HH:MM` is strictly after `now` → today
- otherwise → tomorrow at `HH:MM`

The result is made timezone-aware from the system local zone and stored with its
offset. `now` is a parameter, never read from the clock inside the function —
this is the seam NFR-6 depends on.

### Daemon wake loop

The daemon does not poll on a fixed interval. It sleeps until the next wall-clock
**minute boundary**, because `fire_at` is resolved from `HH:MM` and therefore
always has zero seconds — the boundary is the only instant at which an alarm can
become due.

```
on start:
    acquire pid file (refuse if a live pid is already there)
    detach: fork, setsid, fork, redirect stdio to daemon.log
    install SIGTERM/SIGINT handler -> stop_event.set()
    sweep()                       # startup miss detection (FR-9)
    loop until stop_event:
        sweep()
        stop_event.wait(timeout=seconds_to_next_minute(now))

seconds_to_next_minute(now):
    return 60 - now.second - now.microsecond / 1e6

sweep():
    with store lock:
        for each armed alarm:
            overdue = now - fire_at
            if overdue < 0:            continue                  # not yet
            elif overdue <= GRACE:     ring(alarm); -> fired
            else:                      -> missed                 # no ring
        save if anything changed
```

`GRACE` is 120s. Two details in that loop are load-bearing:

**The sleep target is recomputed from the wall clock every iteration**, never
accumulated. That makes the loop self-correcting: NTP steps, scheduling jitter
and a sweep that takes longer than expected are all absorbed by the next
computation rather than compounding into drift.

**The wait is on a `threading.Event`, not `time.sleep`.** Under
[PEP 475](https://peps.python.org/pep-0475/) Python resumes an interrupted
`time.sleep()` with the remaining delay unless the handler raises, so a
flag-setting SIGTERM handler would leave the daemon sleeping out the rest of its
minute and make `alarm daemon stop` appear to hang for up to 60 seconds.
`Event.wait()` returns the instant the handler sets it.

The grace window is what makes suspend/resume and daemon restarts behave sanely:
a wake that slipped, or one that was skipped entirely, still rings; an alarm that
came due during a three-hour suspend does not. 120s is two wake periods — enough
to absorb one lost wake, small enough that a missed alarm is unambiguous.

`ring()` is best-effort and never raises into the loop: play the sound, raise the
notification, log the outcome of each. A failure in either is logged and the
alarm still becomes `fired` — the alarm did happen, the machine just couldn't be
loud about it.

### Notification (`notify`)

- **Sound:** the first available of `paplay`, `aplay` (Linux), `afplay` (macOS),
  invoked on `~/.alarm-cli/alarm.wav`. If that file is absent it is generated on
  first use — a short sine-wave tone written with the stdlib `wave` module, so
  the repo ships no binary asset (NFR-2). Users can replace it with any WAV.
- **Desktop:** `notify-send -u critical "Alarm" "<message>"` on Linux,
  `osascript -e 'display notification ...'` on macOS.
- Each call is a `subprocess.run` with a short timeout. Missing binary, non-zero
  exit, or timeout is logged and swallowed (NFR-5).

### Concurrency

The client and the daemon both perform read-modify-write on one file. Every such
sequence takes an exclusive `fcntl.flock` on `~/.alarm-cli/alarms.lock` for its
whole duration, and writes go to a temp file in the same directory followed by
`os.replace`, which is atomic on POSIX (FR-12, NFR-7). Reads that don't modify
(`list`, `status`) take the lock in shared mode.

`fcntl` is the reason the project is POSIX-only.

## 4. User flow

```
                         ┌─────────────────────┐
  $ alarm daemon start ─>│ daemon: detached,   │
                         │ wakes on the minute │
                         └──────────┬──────────┘
                                    │ reads/writes under lock
  $ alarm add 07:00 -m standup      ▼
        │                 ┌───────────────────────┐
        └────────────────>│ ~/.alarm-cli/         │
  $ alarm list            │   alarms.json         │
        │<────────────────│   (single source of   │
  $ alarm cancel 1        │    truth)             │
        └────────────────>└───────────────────────┘
                                    ▲
                                    │ 07:00 arrives
                         ┌──────────┴──────────┐
                         │ ring: sound +       │
                         │ notification + log; │
                         │ state -> fired      │
                         └─────────────────────┘
```

Narrative, first use:

1. User runs `alarm daemon start`. The daemon detaches and begins waking on the
   minute.
2. User runs `alarm add 07:00 -m "standup"` at 22:48. The client resolves the
   next 07:00 — tomorrow — appends an `armed` alarm, and prints
   `alarm 1 set for 2026-09-17 07:00 (in 8h 12m)`.
3. The user closes the terminal. The alarm is unaffected; it lives in the file
   and the daemon is not a child of that shell.
4. At 07:00:00 the daemon wakes, sees the alarm due, plays the tone, raises a
   notification reading "standup", logs the ring, and sets the alarm `fired`.
5. `alarm list` is now empty; `alarm list --all` shows alarm 1 as fired at 07:00.

Failure path, daemon down:

1. Alarm 2 is armed for 14:30. The daemon is stopped at 14:00.
2. 14:30 passes with nothing running. Nothing rings and nothing is lost.
3. At 18:20 the user runs `alarm daemon start`. The startup sweep sees alarm 2 is
   overdue by hours, marks it `missed`, and logs it. It does not ring.
4. `alarm list --all` shows alarm 2 as missed, so the user learns what they
   didn't hear.

---

# Known limitations

Each of these is a decision, not a defect. They are listed so nobody re-derives
them or files them as bugs.

1. **An alarm only rings while the daemon runs.** Nothing rings after a reboot
   until `alarm daemon start` is run again. Auto-start would mean installing a
   systemd unit or launch agent, which is exactly the system-level entanglement
   this tool avoids.
2. **Missed alarms never ring.** Firing hours late is worse than not firing —
   it's noise at the wrong moment and it teaches users to distrust the tool.
   `alarm list --all` is how you find out.
3. **No snooze and no dismissal.** A ring is fire-and-forget: one sound, one
   notification. Snooze needs an interactive channel back to a background
   process, and neither a CLI round-trip nor notification action buttons is
   worth the complexity at this size.
4. **No recurring alarms, no countdown timers.** Deliberately cut from v1; both
   are on the backlog in [PLAN.md](PLAN.md).
5. **POSIX only.** `fcntl.flock`, `fork`/`setsid` and the notifier binaries have
   no Windows equivalent here.
6. **Single store, single user.** No namespacing; two users get two stores
   because they get two home directories. Two daemons over one store is
   prevented by the PID file, not by the design.
7. **DST and clock changes.** `fire_at` is stored with the offset in force when
   the alarm was created. An alarm set across a DST boundary fires at the
   absolute instant that offset denotes, which may be an hour off the wall clock
   the user had in mind. A large backwards clock change can push an alarm outside
   the grace window and mark it missed.
8. **Minute granularity, by construction.** Input is `HH:MM`, and the daemon
   wakes only on wall-clock minute boundaries, so sub-minute precision is not
   merely unsupported — the scheduler cannot express it. Adding countdown timers
   (`alarm timer 90s`) means the wake target becomes
   `min(next minute boundary, earliest fire_at)`, not just a new parser.
9. **No config.** Grace window, tone and notifier are constants in
   the source. The only user-tunable knob is replacing `~/.alarm-cli/alarm.wav`.
10. **Sound depends on the environment.** Over SSH with no audio device and no
    notification daemon, a ring degrades to a line in `daemon.log` — technically
    correct and completely useless as an alarm.
11. **No editing.** Changing an alarm means `cancel` then `add`.
