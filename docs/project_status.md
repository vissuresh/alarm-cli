# Project Status

**Last updated:** 2026-09-16
**Version:** 0.1.0 (unreleased)
**Phase:** specified, not implemented

## Where things stand

The design is complete and agreed. No code has been written: the repository
contains documentation only, and has no commits yet.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ⬜ not started (M0) |
| `paths` / `model` / `store` | ⬜ not started (M1) |
| `timeparse` | ⬜ not started (M2) |
| Client commands | ⬜ not started (M3) |
| `notify` | ⬜ not started (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | ⬜ not started |

## Next step

M0 — scaffolding, on branch `feature/scaffolding`. See [PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M0 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-9.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
