"""Thread budget for LightGBM training."""

import os

ML_THREADS_ENV = "DARKSTAR_ML_THREADS"


def ml_thread_count() -> int:
    """LightGBM ``n_jobs``: ``DARKSTAR_ML_THREADS`` if a positive int, else all CPUs.

    Read at call time so a test runner (e.g. parallel pytest workers) can cap
    threads and avoid oversubscribing the machine. Unset keeps the default.
    """
    raw = os.environ.get(ML_THREADS_ENV)
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return os.cpu_count() or 1
