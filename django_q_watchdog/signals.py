from django.dispatch import Signal

# Sent with ``report=`` (a dict) the first time each problem is found.
task_lost = Signal()  # the worker died or was killed for a timeout
task_frozen = Signal()  # still running, but stuck
