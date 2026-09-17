# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0 (unreleased)
**Phase:** in progress — M5 complete

## Where things stand

**The tool works end to end.** `alarm daemon start` detaches a daemon that
survives the terminal it was started from; `alarm add 07:00 -m standup` arms an
alarm; at 07:00 the daemon wakes, plays the tone, raises the notification and
marks the alarm `fired`; an alarm that came due while nothing was running is
marked `missed` instead. `alarm list`, `list --all`, `cancel` and
`daemon stop`/`status` all behave as specified.

What is left is M6: read the help text end to end as a new user would, verify
the README against a clean `uv tool install .`, and cut 0.1.0.

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
| Daemon | ✅ done (M5) — sweep, wake loop, detachment, lifecycle |
| Test suite | ✅ 240 tests in under a second — one starts a real daemon (TD-1), the rest are pure |

## Next step

M6 — release polish: `alarm --help` read end to end, the 0.1.0 changelog entry,
this file flipped to shipped, and the README verified against a clean
`uv tool install .`, on branch `feature/release-0.1.0`. See
[PLAN.md](../PLAN.md).

## Open questions

None blocking. Everything needed to start M6 is decided; the decisions and their
reasoning are recorded in [changelog.md](changelog.md) as DR-1 through DR-16.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
