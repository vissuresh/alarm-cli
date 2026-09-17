# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M1 complete

## Where things stand

The design is complete and agreed. The package installs, and the storage layer
underneath it is built and tested: alarms can be created, persisted, read back
and moved to a terminal state, safely under two writers. Nothing above the store
is wired up yet, so `alarm --version` is still the whole of the user-facing
behaviour.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ✅ done (M0) |
| Package skeleton (`src/alarm_cli/`) | ✅ stubs in place (M0) |
| `paths` / `model` / `store` | ✅ done (M1) |
| `timeparse` | ⬜ not started (M2) |
| Client commands | ⬜ not started (M3) |
| `notify` | ⬜ not started (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | 🟡 71 tests — smoke, paths, model, store; nothing above the store yet |

## Next step

M2 — `timeparse`: `"HH:MM"` plus a `now` to the next occurrence, on branch
`feature/timeparse`. See [PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M2 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-12.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
