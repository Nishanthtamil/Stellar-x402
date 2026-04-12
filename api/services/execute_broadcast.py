"""Fan-out executor SSE payloads to A2A ``SubscribeToTask`` listeners (asyncio queues)."""

from __future__ import annotations

import asyncio
from typing import Any

_lock = asyncio.Lock()
_subscribers: dict[str, list[asyncio.Queue[Any | None]]] = {}


async def ensure_channel(job_id: str) -> None:
    async with _lock:
        _subscribers.setdefault(job_id, [])


async def subscribe(job_id: str, *, maxsize: int = 2000) -> asyncio.Queue[Any | None]:
    q: asyncio.Queue[Any | None] = asyncio.Queue(maxsize=maxsize)
    async with _lock:
        _subscribers.setdefault(job_id, []).append(q)
    return q


async def publish(job_id: str, event: Any) -> None:
    async with _lock:
        qs = list(_subscribers.get(job_id, []))
    for q in qs:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


async def close_subscribers(job_id: str) -> None:
    async with _lock:
        qs = _subscribers.pop(job_id, [])
    for q in qs:
        try:
            await q.put(None)
        except Exception:
            pass
