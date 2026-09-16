# Changelog

Version history and decision records for alarm-cli. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two kinds of entry live here:

- **Releases** — what changed, for users.
- **Decision records (DR-n)** — why the shape of the system is what it is, for
  whoever is tempted to change it. A decision record is never edited after the
  fact; it is superseded by a new one.

---

## [Unreleased]

### Added
- Full documentation set: `README.md`, `project_spec.md`, `PLAN.md`,
  `docs/architecture.md`, `docs/project_status.md`, `docs/TECH_DEBT.md`,
  `CLAUDE.md`.

Nothing is implemented yet. See [project_status.md](project_status.md).

---

# Decision records

## DR-1 — Background daemon plus client CLI (2026-09-16)

**Status:** accepted

**Context.** An alarm has to outlive the terminal that set it, otherwise it is
just `sleep && notify-send` with extra steps. Four shapes were considered:

| Option | Why not |
| --- | --- |
| Foreground blocking process | Dies with the terminal — fails the core requirement. |
| One detached subprocess per alarm | Survives, but listing and cancelling mean tracking a process per alarm; state lives in the process table, which cannot be inspected or repaired. |
| Delegate to `cron` / `systemd` timers | Survives reboot, but entangles a throwaway one-off reminder with system-level configuration, is platform-specific in a second way, and is very hard to test. |
| **Background daemon + client CLI** | Chosen. |

**Decision.** A single long-lived daemon owns ringing. The `alarm` command is a
short-lived client. They share exactly one JSON file and never communicate
directly.

**Consequences.**
- All state is in one inspectable, hand-editable file; the daemon is restartable
  at any moment without loss.
- No IPC, no socket, no protocol, no daemon-side parsing of user input.
- Costs: a PID file and its staleness handling, a lock file for the two writers,
  a poll loop rather than a push, and the standing requirement that the user
  start the daemon (DR-2, DR-3).
- The daemon must fully detach (double fork + `setsid`), or SIGHUP on shell exit
  takes the alarms with it.

## DR-2 — Explicit daemon lifecycle, no auto-start (2026-09-16)

**Status:** accepted

**Context.** `alarm add` could silently spawn the daemon when none is running.

**Decision.** It does not. The daemon is started only by `alarm daemon start`.
Client commands that modify alarms warn on stderr when no daemon is running.

**Consequences.** Implicit background processes are surprising and fail quietly;
an explicit lifecycle means the user always knows whether anything is watching.
The cost is one extra command per login session, and a warning that must actually
be noticed.

## DR-3 — Missed alarms are skipped, not fired late (2026-09-16)

**Status:** accepted

**Context.** If an alarm comes due while the daemon is stopped or the machine is
suspended, it can be fired on the next start, or skipped.

**Decision.** Skipped. An alarm overdue by more than a 60-second grace window is
marked `missed` and never rings. The same sweep handles startup and every tick,
so there is one code path, not two.

**Consequences.** A 07:00 alarm never blares at 11:00. Missed alarms are visible
in `alarm list --all`, so nothing disappears silently. The grace window is the
part that makes this work in practice: it distinguishes a tick delayed by a
second from a three-hour suspend.

**Implication for the schema.** Alarms must store a full local date-time, not a
bare clock time — otherwise a daemon started the next morning cannot tell an
alarm it missed yesterday from one due today. This is FR-10.

## DR-4 — Standard library only, `pytest` for tests (2026-09-16)

**Status:** accepted

**Context.** `typer` + `rich` would give nicer help and tables for free.

**Decision.** Zero runtime dependencies: `argparse`, `json`, `datetime`,
`fcntl`, `subprocess`, `wave`. `pytest` is the single development dependency.

**Consequences.** The tool installs and runs anywhere Python 3.12 does, with no
dependency tree to age. Output formatting is written by hand. `pytest` earns its
exception through `tmp_path` and `monkeypatch`, which the store and notifier
tests lean on heavily.

## DR-5 — Single dotfile directory over XDG paths (2026-09-16)

**Status:** accepted

**Context.** State could follow the XDG base directory spec, splitting data,
runtime and state across three roots.

**Decision.** Everything lives in `~/.alarm-cli/`: `alarms.json`, `alarms.lock`,
`daemon.pid`, `daemon.log`, `alarm.wav`.

**Consequences.** One path to document, one directory to delete to start over,
one place to look when debugging. It ignores XDG convention, and putting a PID
file in `$HOME` rather than `$XDG_RUNTIME_DIR` means stale PID files survive a
reboot — handled by testing liveness with `os.kill(pid, 0)` rather than by
trusting the file.

## DR-6 — Sound and desktop notification, not the terminal bell (2026-09-16)

**Status:** accepted

**Context.** The daemon has no controlling terminal (DR-1), so `\a` on stdout
goes to `daemon.log` and nowhere audible.

**Decision.** Ring by playing a WAV through the system player and raising a
desktop notification. Both are best-effort: a missing binary, non-zero exit or
timeout is logged and swallowed, and the alarm still becomes `fired`.

**Consequences.** The ring is loud in a desktop session and inaudible over a
bare SSH connection, where it degrades to a log line — a real limitation,
recorded as such. The tone is generated with the stdlib `wave` module on first
use rather than shipped, so the repository stays free of binary assets, and users
can replace `~/.alarm-cli/alarm.wav` with anything they like.

## DR-7 — No snooze in v1 (2026-09-16)

**Status:** accepted

**Context.** Snooze was in the initial scope. It requires a channel from the user
back into a running background process at the moment it rings: either a CLI
round-trip (`alarm snooze 1`) with the daemon re-ringing until dismissed, or
notification action buttons.

**Decision.** Cut from v1. A ring is fire-and-forget: one sound, one
notification, state `fired`.

**Consequences.** The daemon needs no ringing state, no repeat scheduling and no
dismissal command, which keeps the tick loop to a single sweep. Snooze stays on
the backlog as a design question rather than an implementation task — adding it
later means revisiting DR-1's "they never communicate directly", which is exactly
the kind of change that deserves its own decision record.

## DR-8 — JSON document over an append-only log (2026-09-16)

**Status:** accepted

**Context.** An append-only write-ahead log was proposed as a replacement for the
single JSON document of DR-5: alarms and cancellations appended as records, with
current state derived by replaying the log.

The log has a real advantage over the document. Today both the client and the
daemon do read-modify-write on one file, which is the entire reason DR-5 needs
`flock` and an atomic rename. With an append-only log, `alarm add` is a single
`write()` on a fd opened `O_APPEND` — POSIX guarantees the seek-to-end and the
write happen with no intervening modification, so concurrent appends cannot
clobber each other, and the add path needs no lock at all. It would also give the
history that `list --all` and TD-4 both want, for free.

What it costs is that no file on disk holds the answer to "what alarms do I
have". Every reader — the daemon on every tick, the client on every `list` — has
to read the whole log and fold it, and the daemon still has to write somewhere
that an alarm has rung, so the writes and the lock come back on the ring path
even though the add path lost them.

**Decision.** Keep the single JSON document of DR-5, written under `flock` with
temp file plus `os.replace`.

**Consequences.**
- The lock-free add path is given up. At this scale it is not yet worth buying:
  a human holds perhaps five to twenty alarms, the file is kilobytes, and `flock`
  plus `os.replace` already makes the two-writer case correct in about ten lines.
- `cat ~/.alarm-cli/alarms.json` continues to show the literal current state.
  That is goal 2 of the project; a log trades it for a history that has to be
  folded to be understood, and a debugging session that starts with replaying
  records in your head is not the one the project promises.
- No compaction. An append-only store grows without bound and eventually needs
  it — and compaction reintroduces exactly the lock-and-rename that the log
  avoided, moved onto a rare code path, which is the kind that is wrong. The
  document is bounded by live alarms, so it needs no equivalent.
- No history. `list --all` and TD-4 get nothing for free; fired and cancelled
  alarms are retained in the document or not at all.

**What would reverse this.** Write volume the document cannot absorb — many
alarms, or many writers — or a requirement for a durable audit trail beyond what
`daemon.log` gives. If either arrives, the replacement is an event-sourced log
with replay-derived state, and compaction bounded by a low-water mark over
records that are entirely terminal.

## DR-9 — Wake on the wall-clock minute, not on a fixed tick (2026-09-16)

**Status:** accepted. Supersedes the `TICK = 1s` and `GRACE = 60s` constants of
DR-3, whose decision — that missed alarms are skipped — stands unchanged.

**Context.** The daemon originally polled every second: 86,400 wakeups a day for
a process that typically has something to do twice. The obvious fix is a longer
interval, 10s or 30s. That is the wrong shape of fix, because it buys fewer
wakeups with proportionally worse accuracy — and the accuracy loss is arbitrary,
since an unaligned tick fires at whatever phase the daemon happened to start at.
Start it at 09:00:17 and a 30s tick wakes at `:17` and `:47` forever, so an alarm
for 07:00:00 rings at 07:00:17.

The observation that resolves it: `fire_at` is resolved from `HH:MM` (FR-1), so
every alarm is due at exactly `:00` seconds. The problem is not how *often* to
wake but at what *phase*.

| Strategy | Wakeups/day | Worst-case lateness |
| --- | --- | --- |
| 1s tick | 86,400 | 1s |
| 10s tick, unaligned | 8,640 | 10s |
| 30s tick, unaligned | 2,880 | 30s |
| minute-aligned | 1,440 | jitter only (~ms) |

**Decision.** The daemon sleeps to the next wall-clock minute boundary rather
than for a fixed interval. `GRACE` becomes 120s — two wake periods.

**Consequences.**
- 60× fewer wakeups than the 1s tick *and* better accuracy than it. This is not
  a trade: alignment dominates every fixed interval on both axes.
- It matters most where an alarm clock actually lives — overnight, on battery,
  where each wakeup pulls the CPU out of a deep idle state for nothing.
- `GRACE` had to move. Its floor is the largest legitimate lateness, and with an
  *unaligned* 60s tick that would be a full 60s, forcing a grace of ~5 minutes
  and blunting the missed-alarm precision DR-3 depends on. Because an aligned
  wake lands *at* the due instant, observed lateness stays near zero regardless
  of period, so 120s need only cover one wake lost entirely.
- **The wait must be on a `threading.Event`, not `time.sleep`.** Under PEP 475
  Python resumes an interrupted `time.sleep()` with the remaining delay unless
  the handler raises, so a flag-setting SIGTERM handler would leave the daemon
  sleeping out the rest of its minute and make `alarm daemon stop` appear to hang
  for up to 60 seconds. At a 1-second tick this bug is invisible; at 60 seconds
  it looks like a broken tool. Recorded in PLAN.md as an M5 test.
- **The sleep target is recomputed from the wall clock each iteration**, never
  accumulated, so NTP steps, jitter and a slow sweep are absorbed rather than
  compounding into drift.
- **New coupling:** the scheduler now assumes every alarm lands on a minute
  boundary. Countdown timers from the backlog are therefore no longer "just a
  second parser" — they make the target `min(next minute boundary, earliest
  fire_at)`. Recorded as limitation 8.

**Rejected alternative.** Sleeping until the earliest armed `fire_at`, which
drops idle wakeups to zero, requires the client to signal the daemon when an
alarm is added — the client→daemon communication DR-1 exists to avoid. It stays
in TD-2, now with a much smaller prize.
