# Architecture

How alarm-cli is put together and why. Requirements and the JSON schema live in
[../project_spec.md](../project_spec.md); this document is the shape of the
system and the movement of data through it.

## The one idea

**The client and the daemon never talk to each other.** They share a file.

```
┌──────────────┐        ┌───────────────────────┐        ┌──────────────┐
│  client      │ write  │  ~/.alarm-cli/        │  read  │  daemon      │
│  (alarm ...) ├───────>│    alarms.json        │<───────┤  (wake loop) │
│  exits in ms │ read   │  + alarms.lock        │  write │  long-lived  │
└──────────────┘<───────┴───────────────────────┴───────>└──────┬───────┘
                                                                │ rings
                                                                ▼
                                                    sound + desktop notification
```

Everything else follows from this:

- there is no socket, no port, no serialisation protocol, no IPC to debug
- the daemon can be killed and restarted at any moment without losing alarms
- `cat ~/.alarm-cli/alarms.json` is a complete debugging session
- the price is a poll loop instead of a push, and a lock file to keep the two
  writers honest

For a tool whose smallest meaningful unit of time is a minute, waking once a
minute is free, and the simplicity is worth far more than the precision a push
would buy.

## Modules and their responsibilities

| Module | Owns | Must not |
| --- | --- | --- |
| `cli.py` | argparse surface, output formatting, exit codes | contain scheduling or storage logic |
| `store.py` | load/save, locking, atomic replace, id allocation | know what an alarm *means* |
| `model.py` | the `Alarm` dataclass, `AlarmState`, JSON (de)serialisation, record invariants | touch the filesystem |
| `timeparse.py` | `"HH:MM"` + `now` → aware `datetime` | read the clock itself |
| `daemon.py` | detach, PID file, wake loop, due/missed decisions | format user-facing output |
| `notify.py` | sound and desktop notification, degradation | raise into the caller |
| `paths.py` | every path under `~/.alarm-cli/` | anything else |

Import direction, strictly one-way:

```
cli ──> store ──> model
 │  ──> timeparse ──> model
 └──> daemon ──> store
              └─> notify
all ──> paths
```

Nothing imports `cli`. That is what makes every layer testable without spawning a
process.

`Alarm` is frozen, and a state change produces a new record
(`alarm.resolve(state, at)`) that the store swaps in by id. A transition is
therefore either fully applied or not applied at all, in memory as well as on
disk, and no list can be left holding a half-updated alarm. The invariants — an
offset on every timestamp, `resolved_at` present exactly when the state is
terminal — are checked on construction, so they hold for records read from a
hand-edited file as much as for ones the client just built.

## Data flow: setting an alarm

```
alarm add 07:00 -m standup
  │
  ├─ cli: parse args
  ├─ timeparse: next_occurrence("07:00", now=datetime.now(tz)) -> 2026-09-17T07:00+05:30
  ├─ store: lock(exclusive)
  │         read alarms.json
  │         append Alarm(id=next_id, state=armed, ...)
  │         next_id += 1
  │         write tmp -> os.replace -> alarms.json
  │         unlock
  ├─ daemon pid check -> warn on stderr if not running
  └─ print "alarm 1 set for 2026-09-17 07:00 (in 8h 12m)"
```

The client exits immediately. It never waits for the daemon to acknowledge
anything, because there is nothing to acknowledge — the daemon will see the new
alarm on its next wake.

## Data flow: a wake

```
on each wake (the next wall-clock minute boundary):
  store: lock(exclusive), read
  for alarm in armed:
      overdue = now - alarm.fire_at
      overdue < 0        -> leave armed
      overdue <= GRACE   -> notify.ring(alarm); state = fired;  resolved_at = now
      overdue >  GRACE   -> state = missed;                     resolved_at = now
  write if dirty, unlock
```

The same sweep runs once at daemon startup, which is the entirety of the
missed-alarm implementation — there is no separate startup path to keep in sync.

### Why the minute boundary

The daemon does not poll on an interval; it sleeps to the next wall-clock minute.
`fire_at` is resolved from `HH:MM`, so every alarm is due at exactly `:00`
seconds — the boundary is the *only* instant at which anything can become due.
Waking on phase rather than on a period is both cheaper and more accurate than
the obvious fixed tick:

| Strategy | Wakeups/day | Worst-case lateness |
| --- | --- | --- |
| 1s tick | 86,400 | 1s |
| 30s tick, unaligned | 2,880 | 30s |
| **minute-aligned** | **1,440** | **jitter only (~ms)** |

An unaligned 30s tick is the worst of both: 30× fewer wakeups bought with 30×
worse accuracy, because the wake phase is wherever the daemon happened to start.
Alignment gives 60× fewer wakeups than a 1s tick *and* better accuracy than it.

This matters most in the situation an alarm clock is actually in: running
overnight, on battery, where every wakeup pulls the CPU out of a deep idle state
to discover there is nothing to do.

The cost is a coupling: the scheduler now assumes every alarm lands on a minute
boundary. Countdown timers from the backlog would break that, and the general
form is `min(next minute boundary, earliest fire_at)`.

### Why `GRACE` is 120s

Without a grace window the daemon would either ring alarms arbitrarily late after
a suspend, or drop alarms whose wake slipped. 120s is two wake periods — enough
to absorb one wake lost entirely, small enough that anything beyond it is
unambiguously a suspend or a restart rather than jitter.

| Situation | Overdue by | Outcome |
| --- | --- | --- |
| normal wake | milliseconds | rings |
| load spike, GC pause, one skipped wake | seconds to ~1 min | rings |
| laptop suspended over the fire time | minutes to hours | missed |
| daemon started the next day | hours | missed |

## Daemon lifecycle

```
alarm daemon start
   ├─ read daemon.pid; os.kill(pid, 0) to test liveness
   │     alive  -> exit 1, "daemon already running (pid N)"
   │     stale  -> remove the pid file and continue
   ├─ fork, setsid, fork        # fully detach from the controlling terminal
   ├─ redirect stdin/stdout/stderr to daemon.log
   ├─ write daemon.pid
   ├─ install SIGTERM/SIGINT -> stop_event.set()
   ├─ sweep()                   # catch anything missed while we were down
   └─ loop until stop_event:
         ├─ sweep()
         ├─ stop_event.wait(timeout = seconds to the next minute boundary)
         └─ on exit: remove daemon.pid, log the shutdown

alarm daemon stop   -> SIGTERM the pid, wait for exit, clean the pid file
alarm daemon status -> report pid + liveness, clearing a stale pid file
```

The double fork is what lets an alarm survive closing the terminal that set it:
after `setsid` the daemon is in its own session with no controlling terminal, so
the shell's SIGHUP on exit never reaches it.

The wait is on a `threading.Event` rather than `time.sleep`, and that is not
stylistic. Under [PEP 475](https://peps.python.org/pep-0475/) Python retries an
interrupted `time.sleep()` with the remaining delay unless the signal handler
raises — so a flag-setting SIGTERM handler would leave the daemon sleeping out
the rest of its minute, and `alarm daemon stop` would appear to hang for up to
60 seconds. `Event.wait()` returns the moment the handler sets it. At a 1-second
tick this bug is invisible; at a 60-second one it looks like a broken tool.

The sleep target is recomputed from the wall clock on every iteration rather than
accumulated, so NTP steps, scheduling jitter and a slow sweep are absorbed by the
next computation instead of compounding into drift.

## Concurrency and durability

Two processes write one file, so every read-modify-write holds
`flock(~/.alarm-cli/alarms.lock, LOCK_EX)` for its full duration — the lock is a
separate file from the data so that replacing the data file cannot drop the lock.
Read-only commands take `LOCK_SH`.

Writes are `tempfile` in the same directory → `os.replace`, which is atomic on
POSIX, with an `fsync` of the file before the rename and of the directory after
it — durable bytes and a durable rename are not the same guarantee. A crash
therefore leaves the store either fully old or fully new, never half-written
(FR-12), and a failed write leaves no temp file behind.

`store` exposes three entry points, and which one a caller reaches for is the
whole of the concurrency discipline:

| Entry point | Lock | For |
| --- | --- | --- |
| `load(root)` | `LOCK_SH` | readers: `list`, `status` |
| `save(store, root)` | `LOCK_EX` | writing a store built from nothing |
| `transaction(root)` | `LOCK_EX`, held across read *and* write | every read-modify-write |

Anything that changes an existing alarm uses `transaction`. `load` then `save`
leaves a window between the two in which the other process can write, and the
second writer wins silently — the exact race the lock exists to prevent.
`transaction` writes back only when the caller actually changed something, which
is what keeps the daemon's once-a-minute sweep over an unchanged store free
(NFR-4).

The locks are per file descriptor, so `load` or `save` *inside* a `transaction`
waits on a lock this process already holds and never returns. The one-way import
direction keeps that from arising by accident: only `cli` and `daemon` open
transactions, and neither calls the other.

The client holds the lock for microseconds; the daemon holds it for one sweep per
minute. Contention is not a concern at this scale, and no lock is ever held
across a `subprocess.run` — `ring()` happens with the alarm already committed.

## Testing seams

The design exists in the shape it does largely so that it can be tested without
sleeping or waiting:

- **`now` is always a parameter.** `timeparse.next_occurrence` and the sweep both
  take the current time from the caller. Tests pass a fixed `datetime`; nothing
  mocks the clock globally.
- **`store` takes a root directory.** Tests point it at `tmp_path`; no test ever
  touches the real `~/.alarm-cli`. Where the root cannot be passed as an
  argument — the M5 integration test drives a real daemon through the console
  script — `ALARM_CLI_HOME` redirects it across the process boundary (DR-11).
- **`notify` is injectable and subprocess-shaped.** Tests assert on the commands
  that *would* have run; nothing plays audio in CI.
- **The wake loop is one function.** `sweep()` is called directly in tests; the
  loop around it is trivial enough not to need coverage.
- **The sleep target is a pure function of `now`.** `seconds_to_next_minute` is
  unit-tested against fixed times — at `:00`, at `:59.999`, mid-minute — without
  any waiting.

The only things that need a real process are daemon start/stop and detachment,
which is why they are the single deliberately-thin area of the test suite.
