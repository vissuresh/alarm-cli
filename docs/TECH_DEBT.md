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

Nothing yet — no code has been written. The entries below are debt the design
already commits to, recorded now so it is not discovered later as a surprise.

### TD-1 — Daemon start/stop is thinly tested

**Accepted because:** detachment (double fork, `setsid`, stdio redirection to
`daemon.log`) cannot be tested without spawning a real process, and real
processes in a test suite are slow and flaky.

**Cost:** the one part of the system that fails hardest — the daemon not actually
detaching, so alarms die with the terminal — has the least coverage. Everything
else is unit-tested against a fixed `now`.

**Paying it off:** one integration test that starts a real daemon with the
notifier stubbed, confirms the PID file, confirms the process survives its
parent's exit, sets a near-future alarm, and observes `fired`. Scheduled in M5.

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

_(none yet)_
