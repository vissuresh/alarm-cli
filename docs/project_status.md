# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M4 complete

## Where things stand

The client half of the tool works. `alarm add`, `alarm list`, `alarm list --all`
and `alarm cancel` all do what the spec says, on top of a store that two
processes can safely share.

Ringing works too, in the sense that `notify.ring()` plays a tone and raises a
desktop notification on whatever the machine has, and degrades to a log line on
whatever it hasn't.

What is missing is the thing that calls it. There is no daemon yet, so an alarm
sits `armed` past its time and nothing notices. That is M5, and it is the half
that makes this an alarm clock rather than a list.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ✅ done (M0) |
| Package skeleton (`src/alarm_cli/`) | ✅ stubs in place (M0) |
| `paths` / `model` / `store` | ✅ done (M1) |
| `timeparse` | ✅ done (M2) |
| Client commands | ✅ done (M3) — `add`, `list`, `list --all`, `cancel` |
| `notify` | ✅ done (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | 🟡 183 tests — everything built so far; no test plays audio or waits on a clock |

## Next step

M5 — the daemon: `sweep()`, the minute-aligned wake loop, detachment, and
`start`/`stop`/`status`, on branch `feature/daemon`. See [PLAN.md](../PLAN.md).
It is the riskiest milestone and the one with the least test coverage by
design (TD-1).

## Open questions

None blocking. Everything needed to start M5 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-15.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
