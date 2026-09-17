# MVP Plan

Build order for alarm-cli v0.1.0. The spec is settled
([project_spec.md](project_spec.md)); this is the sequence for turning it into
working software.

Each milestone is one branch, one PR, one merge to `master`. Milestones are
ordered so that every one leaves the repo in a working, testable state, and so
that the riskiest unknown (detaching a daemon) is not the last thing attempted.

> **All milestones are complete as of 0.1.0 (2026-09-17).** This file is kept as
> the record of the order things were built in and, below, of what was
> deliberately left out. Current state lives in
> [docs/project_status.md](docs/project_status.md).

## M0 — Scaffolding

**Branch:** `feature/scaffolding`

- `pyproject.toml`: name `alarm-cli`, `requires-python = ">=3.12"`, no runtime
  dependencies, console script `alarm = alarm_cli.cli:main`, `pytest` as the only
  dev extra
- `src/alarm_cli/` package with empty modules per the layout in the spec
- `tests/` with a smoke test that imports the package and runs `alarm --version`
- `.gitignore`

**Done when:** `uv sync` and `uv run pytest` both succeed and `uv run alarm
--version` prints a version.

## M1 — Model and store

**Branch:** `feature/store`

- `paths.py`: resolve `~/.alarm-cli/` and its five files, honouring an override
  root so tests can redirect it
- `model.py`: `AlarmState` enum, `Alarm` dataclass, `to_dict`/`from_dict`
- `store.py`: `load()`, `save()`, `flock` locking, temp-file + `os.replace`,
  `next_id` allocation, missing-file default, malformed-JSON refusal

**Done when:** tests cover round-tripping, an absent store, a corrupt store, id
monotonicity across cancellation, and that a simulated crash between write and
replace leaves the old file intact. Nothing touches the real home directory.

## M2 — Time resolution

**Branch:** `feature/timeparse`

- `next_occurrence(hhmm: str, now: datetime) -> datetime`, timezone-aware
- rejects malformed input with a message naming the accepted format

**Done when:** tests cover today-vs-tomorrow on both sides of the boundary, exact
equality with `now` (→ tomorrow), midnight, `23:59`, and a table of malformed
inputs (`7:00`, `25:00`, `07:60`, `0700`, empty, `abc`).

## M3 — Client commands

**Branch:** `feature/cli-commands`

- `add`, `list`, `list --all`, `cancel`
- output formatting: the table, the relative "in 8h 12m", the resolved absolute
  time on `add`
- exit codes: 0 / 1 / 2 per the spec

**Done when:** every FR-1 through FR-5 assertion has a test, including unknown
and non-armed ids. The daemon-not-running warning (FR-11) is stubbed here and
wired in M5.

## M4 — Notification

**Branch:** `feature/notify`

- player and notifier detection with the documented fallback order
- WAV tone generated with the stdlib `wave` module on first use
- every failure path logged and swallowed

**Done when:** tests assert the exact commands chosen for a Linux-like and a
macOS-like environment, and that a missing binary, a non-zero exit and a timeout
each degrade to a log line rather than an exception. No test plays audio.

## M5 — Daemon

**Branch:** `feature/daemon`

- `sweep()`: the due / missed / not-yet decision, including the grace window
- `seconds_to_next_minute()` and the minute-aligned wake loop
- signal handling via a `threading.Event` the loop waits on
- `start` with double-fork detachment, `stop`, `status`, PID-file liveness and
  stale-file cleanup
- the FR-11 warning wired into the client

**Done when:** `sweep()` is unit-tested against a fixed `now` for every branch of
the state machine (not yet due, within grace, beyond grace, already terminal);
`seconds_to_next_minute()` is tested at `:00`, mid-minute and `:59.999`; and one
integration test starts a real daemon, sets a near-future alarm with the notifier
stubbed, and observes the state reach `fired`. That test must also confirm
`alarm daemon stop` returns promptly rather than waiting out the current minute
— the PEP 475 trap.

## M6 — Release polish

**Branch:** `feature/release-0.1.0`

- `alarm --help` reads well end to end
- `docs/changelog.md` gets its 0.1.0 entry
- `docs/project_status.md` flipped to shipped
- README install instructions verified against a clean `uv tool install .`

**Done when:** a new user can follow the README from clone to a ringing alarm
without reading anything else.

## Backlog — after v1

Not scheduled. Listed so the cuts stay visible and so nobody re-proposes them
without reading why they were cut ([Known
limitations](project_spec.md#known-limitations)).

| Item | Note |
| --- | --- |
| Countdown timers (`alarm timer 10m`) | Not just a second parser: sub-minute fire times break the minute-aligned wake, so the sleep target becomes `min(next minute boundary, earliest fire_at)`. |
| Recurring alarms | Needs a repeat rule on the model and a next-fire recomputation after each ring. |
| Snooze / dismiss | Needs an interactive channel back into the daemon. The real design question, not the implementation. |
| Reboot persistence | A systemd user unit or launch agent, shipped as an opt-in `alarm daemon install`. |
| Config file | Once there are three constants worth tuning, not before. |
| `alarm edit <id>` | Sugar over cancel + add. |
