"""Place a worker on its configured CPU when the platform supports affinity."""

import os


def pin_to_cpu(cpu: int | None) -> None:
    """Apply one CPU affinity without preventing startup when it is unavailable."""
    if cpu is None or not hasattr(os, "sched_setaffinity"):
        return
    try:
        os.sched_setaffinity(0, {cpu})
    except OSError:
        return
