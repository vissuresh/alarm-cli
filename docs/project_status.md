# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M0 complete

## Where things stand

The design is complete and agreed. The package now exists and installs, but no
behaviour does: `alarm --version` is the whole of it, and every module below
`cli` is a documented stub.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ✅ done (M0) |
| Package skeleton (`src/alarm_cli/`) | ✅ stubs in place (M0) |
| `paths` / `model` / `store` | ⬜ not started (M1) |
| `timeparse` | ⬜ not started (M2) |
| Client commands | ⬜ not started (M3) |
| `notify` | ⬜ not started (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | 🟡 smoke test only (M0) |

## Next step

M1 — `paths`, `model` and `store`, on branch `feature/store`. See
[PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M1 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-10.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
