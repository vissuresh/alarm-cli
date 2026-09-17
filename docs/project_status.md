# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M2 complete

## Where things stand

The design is complete and agreed. The package installs, and both layers under
the commands are built and tested: alarms can be created, persisted, read back
and moved to a terminal state safely under two writers, and a typed `HH:MM`
resolves to the next instant it names. Nothing is wired up to a command yet, so
`alarm --version` is still the whole of the user-facing behaviour.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ✅ done (M0) |
| Package skeleton (`src/alarm_cli/`) | ✅ stubs in place (M0) |
| `paths` / `model` / `store` | ✅ done (M1) |
| `timeparse` | ✅ done (M2) |
| Client commands | ⬜ not started (M3) |
| `notify` | ⬜ not started (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | 🟡 107 tests — smoke, paths, model, store, timeparse; no command is covered yet |

## Next step

M3 — the client commands `add`, `list`, `list --all` and `cancel`, on branch
`feature/cli-commands`. See [PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M3 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-13.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
