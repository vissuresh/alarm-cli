# Technical Debt

Known compromises, and work knowingly deferred. This is not the backlog —
features that were never built live in [PLAN.md](../PLAN.md), and cuts that were
deliberate and permanent live in
[Known limitations](../project_spec.md#known-limitations). What belongs here is
work that is *owed*: something that should be better than it is.

**Entry format:** `TD-n`, what it is, why it was accepted, what it costs, and what
paying it off looks like.

---

## Open

### TD-2 — Waking every minute rather than at the next fire time

**Accepted because:** a minute-aligned wake has one code path, is immediately
correct when alarms are added or cancelled underneath it, and needs no
communication between client and daemon. DR-9 already cut the obvious waste here:
1,440 wakeups a day instead of 86,400.

**Cost:** 1,440 wakeups a day for a process that typically has something to do
twice. Negligible on a desktop; still not *nothing* on a laptop running
overnight on battery, which is exactly when an alarm daemon is alive.

**Paying it off:** sleep until the earliest armed `fire_at` instead of the next
boundary, which drops idle wakeups to zero. The catch is that the daemon must
then learn about a newly added alarm before its next scheduled wake, which means
the client signalling the daemon — reintroducing the client→daemon communication
DR-1 deliberately avoids. It needs its own decision record before it is worth
doing, and at 1,440 wakeups the remaining prize is small.

### TD-3 — Configuration constants are hard-coded

**Accepted because:** `GRACE`, the player list and the notifier command have no
second known-good value yet, and a config file invented before there is
demand is a schema to maintain forever.

**Cost:** changing any of them means editing source. Users on unusual setups
(a different notifier, a machine that suspends constantly and wants a longer
grace window) have no recourse.

**Paying it off:** once a third constant genuinely wants tuning, a single
`~/.alarm-cli/config.json` with those keys — not before.

### TD-4 — `ring()` failures are invisible outside the log

**Accepted because:** an alarm that cannot be made audible has still happened,
and failing the state transition would leave alarms stuck `armed` and re-ringing
forever.

**Cost:** if `notify-send` is missing, every alarm silently "works" while the
user hears nothing. The only evidence is `daemon.log`.

**Paying it off:** record the ring outcome on the alarm itself (e.g.
`fired`/`fired_silently`) so `alarm list --all` can show it, and warn once at
daemon start when no player or notifier is available on the machine.

---

## Paid off

### TD-1 — Daemon start/stop is thinly tested (paid off in M5, 2026-09-17)

**Was:** detachment — double fork, `setsid`, stdio redirection to `daemon.log` —
cannot be tested without spawning a real process, so the part of the system that
fails hardest had the least coverage.

**Paid by:** `test_a_real_daemon_detaches_rings_and_stops_promptly`. It starts a
real daemon through the console script, confirms the PID file holds a live PID
*after the starting command has exited* (so the daemon is not a child of the
test), watches an already-due alarm reach `fired`, confirms the ring reached
both stub binaries, and times `alarm daemon stop` to catch the PEP 475 trap —
a `time.sleep()` loop would block until the next minute boundary. The stubs are
symlinks to `echo` on an otherwise empty `PATH`, so nothing audible can happen
even on a machine with a sound card.

**What is still thin:** that the daemon ignores SIGHUP when its terminal closes
is argued from `setsid` rather than asserted — testing it needs a pty and a
shell, which is more machinery than the risk justifies. It remains the one
place where reading the code is the evidence.
