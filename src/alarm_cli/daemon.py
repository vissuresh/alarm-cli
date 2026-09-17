"""Detachment, the PID file, the wake loop, and the due/missed decision.

Wakes on the wall-clock minute boundary rather than on an interval, waits on a
``threading.Event`` so SIGTERM is seen immediately (PEP 475), and formats no
user-facing output.

Implemented in M5.
"""
