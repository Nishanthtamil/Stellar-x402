"""In-memory activity feed for dashboard / vault TX-style timelines (demo)."""

from __future__ import annotations

import itertools
import time
from collections import deque
from threading import Lock
from typing import Any

_lock = Lock()
_events: deque[dict[str, Any]] = deque(maxlen=200)
_id = itertools.count(1)


def push_event(**kwargs: Any) -> dict[str, Any]:
    with _lock:
        ev = {"id": next(_id), "ts": time.time(), **kwargs}
        _events.append(ev)
        return ev


def get_events() -> list[dict[str, Any]]:
    with _lock:
        return list(_events)


def clear_events() -> None:
    with _lock:
        _events.clear()
