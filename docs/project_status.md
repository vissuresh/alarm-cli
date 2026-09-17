# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M3 complete

## Where things stand

The client half of the tool works. `alarm add`, `alarm list`, `alarm list --all`
and `alarm cancel` all do what the spec says, on top of a store that two
processes can safely share.

Nothing rings yet: there is no daemon and no notifier, so an alarm sits `armed`
until something comes along to fire it. That is M4 and M5, and it is the half
that makes the tool an alarm clock rather than a list.

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
| `notify` | ⬜ not started (M4) |
| Daemon | ⬜ not started (M5) |
| Test suite | 🟡 156 tests — everything built so far; nothing rings yet to test |

## Next step

M4 — `notify`: player and notifier detection, the generated WAV tone, and the
failure paths that degrade to a log line, on branch `feature/notify`. See
[PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M4 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-14.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
