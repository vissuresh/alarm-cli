# Project Status

**Last updated:** 2026-09-17
**Version:** 0.1.0
**Phase:** shipped — M0 through M6 complete

## Where things stand

**The tool works end to end.** `alarm daemon start` detaches a daemon that
survives the terminal it was started from; `alarm add 07:00 -m standup` arms an
alarm; at 07:00 the daemon wakes, plays the tone, raises the notification and
marks the alarm `fired`; an alarm that came due while nothing was running is
marked `missed` instead. `alarm list`, `list --all`, `cancel` and
`daemon stop`/`status` all behave as specified.

The release is cut. `uv tool install .` was run against a clean tool directory
and driven through the whole README: install, `daemon start`, `add`, `list`,
an alarm coming due and ringing on the minute boundary, `list --all`,
`daemon stop`. The daemon woke 3ms after the boundary it was aiming at.

| Area | Status |
| --- | --- |
| Requirements (PRD) | ✅ settled — [project_spec.md](../project_spec.md) |
| Technical design (EDD) | ✅ settled — [project_spec.md](../project_spec.md), [architecture.md](architecture.md) |
| Build plan | ✅ settled — [PLAN.md](../PLAN.md) |
| Packaging (`pyproject.toml`) | ✅ done (M0) |
| Package skeleton (`src/alarm_cli/`) | ✅ done — no stub modules remain |
| `paths` / `model` / `store` | ✅ done (M1) |
| `timeparse` | ✅ done (M2) |
| Client commands | ✅ done (M3) — `add`, `list`, `list --all`, `cancel` |
| `notify` | ✅ done (M4) |
| Daemon | ✅ done (M5) — sweep, wake loop, detachment, lifecycle |
| Release polish (M6) | ✅ done — help text, changelog, verified install |
| Test suite | ✅ 246 tests in under a second — one starts a real daemon (TD-1), the rest are pure |

## Next step

Nothing scheduled. 0.1.0 is the whole of what was planned, and the project's
third goal is small and finished over large and growing — the backlog in
[PLAN.md](../PLAN.md) is a record of what was cut, not a queue.

The open debt is TD-2 (1,440 idle wakeups a day), TD-3 (constants are not
configurable) and TD-4 (a ring that failed is only visible in `daemon.log`).
TD-4 is the one a real user is most likely to feel.

## Open questions

None. The decisions and their reasoning are recorded in
[changelog.md](changelog.md) as DR-1 through DR-16.

## Update protocol

This file is updated as part of every feature or fix, before the commit — see the
documentation rules in [../CLAUDE.md](../CLAUDE.md). A stale status file is worse
than no status file.
