"""Sound and desktop notification, with degradation.

Never raises into its caller: a missing player, a non-zero exit and a timeout
each degrade to a log line, because an alarm that cannot be made audible has
still happened.

Implemented in M4.
"""
