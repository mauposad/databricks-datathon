"""In-process caches that keep the SQL warehouse off the hot path.

* `TTLCache`: bounded, thread-safe, time-limited cache for search results.
* `Refreshing`: one reference value (service list, place list) served stale-while-revalidate. The first read can be
  answered from a snapshot file shipped with the app (see scripts/snapshot_reference.py), and expired values are
  refreshed in a background thread, so page loads never wait on the warehouse once a value exists.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable

log = logging.getLogger(__name__)

SNAPSHOT = Path(__file__).resolve().parent / "reference_snapshot.json"


class TTLCache:
    def __init__(self, ttl: float, maxsize: int = 256):
        self.ttl, self.maxsize = ttl, maxsize
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if time.time() - hit[0] >= self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return hit[1]

    def set(self, key: Hashable, value: Any) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


def _load_snapshot() -> dict[str, Any]:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable %s: %s", SNAPSHOT.name, e)
        return {}


class Refreshing:
    """A value loaded by `loader`, refreshed in the background once older than `ttl` seconds.

    `parse` turns the snapshot's JSON for `snapshot_key` into the same shape `loader` returns.
    """

    RETRY_AFTER = 60.0  # seconds to wait before retrying a failed background refresh

    def __init__(self, snapshot_key: str, loader: Callable[[], Any], ttl: float,
                 parse: Callable[[Any], Any] = lambda v: v):
        self.snapshot_key, self.loader, self.ttl, self.parse = snapshot_key, loader, ttl, parse
        self._value: Any = None
        self._loaded_at = 0.0       # 0 = came from the snapshot (treated as expired)
        self._next_try = 0.0
        self._refreshing = False
        self._lock = threading.Lock()

    def get(self) -> Any:
        with self._lock:
            if self._value is None:
                snap = _load_snapshot().get(self.snapshot_key)
                if snap:
                    self._value = self.parse(snap)
                    log.info("Serving %s from snapshot until the warehouse answers", self.snapshot_key)
            value = self._value
        if value is None:  # no snapshot and never loaded: the caller has to wait this once
            return self._load_now()
        self._maybe_refresh()
        return value

    def prefetch(self) -> None:
        """Load (or refresh) now, in the calling thread. Used by the warm-up."""
        self._load_now()

    def _load_now(self) -> Any:
        value = self.loader()
        with self._lock:
            self._value, self._loaded_at = value, time.time()
        return value

    def _maybe_refresh(self) -> None:
        now = time.time()
        with self._lock:
            if self._refreshing or now - self._loaded_at < self.ttl or now < self._next_try:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh, name=f"refresh-{self.snapshot_key}", daemon=True).start()

    def _refresh(self) -> None:
        try:
            self._load_now()
        except Exception as e:  # keep serving the old value
            log.warning("Background refresh of %s failed: %s", self.snapshot_key, e)
            with self._lock:
                self._next_try = time.time() + self.RETRY_AFTER
        finally:
            with self._lock:
                self._refreshing = False
