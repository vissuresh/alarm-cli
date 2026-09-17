"""Every path under ``~/.alarm-cli/``, and nothing else.

Owns the five files listed in the README: ``alarms.json``, ``alarms.lock``,
``daemon.pid``, ``daemon.log`` and ``alarm.wav``. The root is overridable so
that no test ever touches a real home directory.

Implemented in M1.
"""
