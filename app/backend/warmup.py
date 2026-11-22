"""Start the SQL warehouse ahead of the first search.

The serverless warehouse auto-stops when idle, and the first query after that waits for it to start. The app calls
`trigger()` at boot and the front end calls POST /api/warmup when the page loads, so the warehouse is starting while
the user is still typing. It runs in a background thread and never blocks a request.
"""
from __future__ import annotations

import logging
import threading
import time

from . import config, sql

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last = float("-inf")


def trigger(reason: str) -> bool:
    """Start a warm-up unless one ran in the last WARMUP_COOLDOWN seconds. Returns whether one was started."""
    global _last
    if not config.WARMUP:
        return False
    with _lock:
        now = time.monotonic()
        if now - _last < config.WARMUP_COOLDOWN:
            return False
        _last = now
    threading.Thread(target=_run, args=(reason,), name="warmup", daemon=True).start()
    return True


def _run(reason: str) -> None:
    from .adapters import get_adapter  # late import: adapters import sql, which imports config
    t0 = time.monotonic()
    try:
        sql.query("SELECT 1 AS ok")
        log.info("Warehouse warm (%s) in %.1fs", reason, time.monotonic() - t0)
        get_adapter().prefetch()
    except Exception as e:  # warm-up is best effort
        log.warning("Warm-up (%s) failed after %.1fs: %s", reason, time.monotonic() - t0, e)
