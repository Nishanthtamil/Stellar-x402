"""A2A task documents: Redis when available, else process memory (TTL-pruned)."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

_TTL_SEC = int(os.getenv("A2A_TASK_TTL_SEC", "604800"))
_LOCK = threading.Lock()
_MEM: dict[str, dict[str, Any]] = {}
_REDIS = None
_REDIS_FAILED = False

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None  # type: ignore[misc, assignment]


def _redis():
    global _REDIS, _REDIS_FAILED
    if _REDIS_FAILED or redis_lib is None:
        return None
    if _REDIS is not None:
        return _REDIS
    url = (os.getenv("REDIS_URL") or "").strip() or "redis://127.0.0.1:6379/0"
    try:
        r = redis_lib.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.35)
        r.ping()
        _REDIS = r
        return r
    except Exception:
        _REDIS_FAILED = True
        return None


def _key(tid: str) -> str:
    return f"a2a:task:{tid}"


def _index_key() -> str:
    return "a2a:tasks:z"


def remember_task(task_id: str, document: dict[str, Any]) -> None:
    doc = dict(document)
    doc["_stored_at"] = time.time()
    r = _redis()
    if r:
        r.set(_key(task_id), json.dumps(doc), ex=_TTL_SEC)
        r.zadd(_index_key(), {task_id: doc["_stored_at"]})
        r.expire(_index_key(), _TTL_SEC)
        return
    with _LOCK:
        _prune_mem_unlocked()
        _MEM[task_id] = doc


def _prune_mem_unlocked() -> None:
    cutoff = time.time() - _TTL_SEC
    stale = [k for k, v in _MEM.items() if v.get("_stored_at", 0) < cutoff]
    for k in stale:
        _MEM.pop(k, None)


def get_task(task_id: str) -> dict[str, Any] | None:
    r = _redis()
    if r:
        raw = r.get(_key(task_id))
        if not raw:
            return None
        return json.loads(raw)
    with _LOCK:
        _prune_mem_unlocked()
        d = _MEM.get(task_id)
        return dict(d) if d else None


def list_tasks(
    *,
    status_state: str | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    r = _redis()
    if r:
        ids = r.zrevrange(_index_key(), 0, max(0, page_size - 1))
        out: list[dict[str, Any]] = []
        for tid in ids:
            tid_s = tid.decode() if isinstance(tid, bytes) else str(tid)
            g = get_task(tid_s)
            if not g:
                continue
            st = (g.get("status") or {}).get("state")
            if status_state and st != status_state:
                continue
            out.append(g)
        return out
    with _LOCK:
        _prune_mem_unlocked()
        rows = list(_MEM.values())
    rows.sort(key=lambda d: d.get("_stored_at", 0), reverse=True)
    out = []
    for g in rows[:page_size]:
        st = (g.get("status") or {}).get("state")
        if status_state and st != status_state:
            continue
        out.append(g)
    return out
