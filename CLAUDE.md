# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goals

A one-off alarm clock for the terminal on Linux and macOS. Set an alarm for a
clock time, close the terminal, get interrupted by a sound and a desktop
notification when it fires.

Three goals shape every decision here, in priority order:

1. **Zero runtime dependencies.** Standard library only. `pytest` is the single
   development dependency and had to earn it.
2. **All state inspectable.** One JSON file, hand-editable, in one directory.
   `cat ~/.alarm-cli/alarms.json` should be a complete debugging session.
3. **Small and finished over large and growing.** Recurring alarms, timers,
   snooze and reboot persistence were each considered and cut. Re-adding one is a
   design decision needing a record, not a ticket.

**Current state: documentation only.** No code exists yet, and the repository has
no commits. Start from [PLAN.md](PLAN.md) — M0 is the scaffolding.

## Architecture overview

A **client** (the `alarm` command, lives milliseconds) and a **daemon** (rings
alarms, lives all session) that share exactly one JSON file and never talk to
each other directly. No socket, no IPC, no protocol.

```
alarm add/list/cancel ──> ~/.alarm-cli/alarms.json <── daemon wake loop (:00)
                          (+ alarms.lock)                    └─> sound + notification
```

Consequences that come up constantly:

- **The daemon polls; it is never pushed to.** The client writes and exits; the
  daemon notices on its next wake. Do not add a wakeup signal without a decision
  record (see TD-2).
- **It wakes on the wall-clock minute boundary, not on an interval.** Every
  `fire_at` has zero seconds because input is `HH:MM`, so the boundary is the
  only instant anything can be due. Recompute the sleep target from the clock
  each iteration — never accumulate — and wait on a `threading.Event`, not
  `time.sleep`, or SIGTERM won't be seen until the minute is up (PEP 475).
- **An alarm only rings while the daemon runs**, and an alarm overdue by more
  than the 120-second grace window is marked `missed` and never rings. One
  `sweep()` implements due / missed / not-yet, and runs both at startup and on
  every wake — there is no separate startup path.
- **Alarms store a full local date-time with UTC offset**, not a bare clock time.
  Missed detection across days depends on this.
- **Both processes write one file**, so every read-modify-write holds an
  exclusive `flock` on `alarms.lock` and writes via temp file + `os.replace`.
- **`now` is always a parameter**, never read inside logic. This is the seam the
  whole test suite rests on.
- **The daemon double-forks and `setsid`s.** That detachment is what makes alarms
  survive closing the terminal; if it breaks, everything else is decoration.

Module boundaries, import direction and the data flows are in
[docs/architecture.md](docs/architecture.md). Read it before adding a module.

## Dependencies

Minimize aggressively. Adding a runtime dependency contradicts goal 1 — it needs
a decision record in [docs/changelog.md](docs/changelog.md) arguing why the
standard library is insufficient, not just less convenient. This applies to
`rich`, `click`/`typer`, `python-dateutil` and friends, all of which were
considered and rejected in DR-4.

Development dependencies: `pytest` only. No linter or type checker is configured;
if one is added, wire it into the pre-push commands below in the same change.

## Code quality

- Write for the reader who is debugging at 07:00 because an alarm didn't ring.
- Keep the layering one-way (`cli` → `store`/`daemon`/`timeparse` → `model`).
  Nothing imports `cli`; nothing below `cli` formats user-facing output.
- Pure functions where the domain allows: parsing and the due/missed decision
  take their inputs and return results, and do not touch the clock or the disk.
- `notify` never raises into the wake loop. A ring that can't be heard is logged
  and the alarm still becomes `fired`.
- Errors the user caused (bad time, unknown id) exit 1 with a message naming the
  accepted form. Errors they didn't cause get a traceback — don't swallow bugs.
- Never silently reset a corrupt `alarms.json`; refuse and tell the user where it
  is. Resetting destroys alarms.
- Comment the *why* of a non-obvious constant (why `GRACE` is two wake periods),
  not the what.

## Commands

The package does not exist yet; these are the commands M0 must make true, and
they are the ones to use from M1 onward.

```sh
uv sync                              # create the venv, install dev deps
uv run pytest                        # full test suite
uv run pytest tests/test_store.py    # one file
uv run pytest tests/test_store.py::test_atomic_write   # one test
uv run pytest -k "missed"            # by name
uv run pytest -x -q                  # stop at first failure, quiet

uv run alarm --help                  # run the CLI from the working tree
uv tool install .                    # install `alarm` on PATH
```

Debugging a live daemon:

```sh
uv run alarm daemon status
tail -f ~/.alarm-cli/daemon.log
cat ~/.alarm-cli/alarms.json
rm -rf ~/.alarm-cli                  # full reset
```

## Testing instructions

- **No test sleeps for real time and no test reads the wall clock.** Pass a fixed
  `datetime` as `now`. A test that waits for a second to pass is a bug.
- **No test touches the real `~/.alarm-cli`.** Point the store root at
  `tmp_path`. A test that writes to a real home directory is a bug, and will
  eventually delete someone's alarms.
- **No test plays audio or raises a notification.** Stub the subprocess layer and
  assert on the command that would have run.
- Cover the state machine exhaustively — not yet due, within grace, beyond grace,
  already terminal — since that is where the product's actual behaviour lives.
- The sleep target is a pure function of `now`; test it at `:00`, mid-minute and
  `:59.999` rather than by waiting for a boundary to arrive.
- Cover the store's failure paths: absent file, corrupt JSON, higher
  `schema_version`, crash between write and replace.
- The one place real processes are acceptable is the daemon start/stop
  integration test (see TD-1). Keep it to one.

Before pushing:

```sh
uv run pytest
uv run alarm --help        # sanity-check the CLI still starts
```

## Documentation

Keep these current; they are the contract, not a description of it.

| Document | Contains |
| --- | --- |
| [project_spec.md](project_spec.md) | Full requirements (PRD), technical design (EDD), JSON schema, command specs, known limitations |
| [docs/architecture.md](docs/architecture.md) | System design, module responsibilities, data and user flow |
| [docs/changelog.md](docs/changelog.md) | Version history and decision records (DR-n) |
| [docs/project_status.md](docs/project_status.md) | Current progress — what is built and what is next |
| [PLAN.md](PLAN.md) | MVP build order, milestone acceptance criteria, post-v1 backlog |
| [docs/TECH_DEBT.md](docs/TECH_DEBT.md) | Accepted compromises (TD-n) and what paying each off looks like |
| [README.md](README.md) | User-facing: install, usage, where state lives |

Rules:

- Changing behaviour means updating `project_spec.md` in the **same** change, not
  afterwards. A spec that lags the code is worse than no spec.
- Changing the shape of the system — a new module, a new cross-module dependency,
  a different flow — means updating `docs/architecture.md`.
- Every architectural decision gets a **decision record** in
  `docs/changelog.md`: context, the options rejected, the decision, the
  consequences. Records are never edited after the fact; supersede them.
- Every finished milestone updates `docs/project_status.md`.
- Every knowing compromise gets a TD entry with its payoff path.
- **Always run `/update-docs-and-commit` before committing** each feature or fix,
  so documentation and code land together.

## Repository etiquette

### Branching

- Always create a feature or fix branch before starting work.
- **Never commit directly to `master`.** (The single exception is the very first
  commit, which has to create the branch.)
- Naming: `feature/description`, `fix/description`.

### Workflow for changes

1. Create a new branch off `master`.
2. Develop and commit on the branch.
3. Test locally — `uv run pytest` — before pushing.
4. Push the branch.
5. Open a PR into `master`.

### Commits

- Clear, concise messages describing the change and, where it isn't obvious, why.
- One focused change per commit. Don't mix a refactor with a behaviour change.

### Pull requests

- All changes to `master` go through a PR.
- **Never force push to `master`.**
- The description says what changed and why, and links the milestone or issue.

### Before pushing

```sh
uv run pytest
uv run alarm --help
```
