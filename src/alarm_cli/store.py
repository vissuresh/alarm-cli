"""Load and save ``alarms.json``: locking, atomic replace, id allocation.

Knows how alarms are persisted, not what they mean. Every read-modify-write
holds an exclusive ``flock`` on ``alarms.lock`` and lands via temp file plus
``os.replace``.

Implemented in M1.
"""
