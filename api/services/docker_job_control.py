"""Track per-job Docker containers and honor cooperative cancel."""

from __future__ import annotations

import threading
from typing import Callable

import docker

_lock = threading.Lock()
_container_ids: dict[str, str] = {}
_cancel_requested: set[str] = set()


def register_container(job_id: str, container_id: str) -> None:
    with _lock:
        _container_ids[job_id] = container_id


def unregister_container(job_id: str) -> None:
    with _lock:
        _container_ids.pop(job_id, None)


def request_cancel(job_id: str) -> None:
    with _lock:
        _cancel_requested.add(job_id)


def clear_cancel(job_id: str) -> None:
    with _lock:
        _cancel_requested.discard(job_id)


def is_cancel_requested(job_id: str) -> bool:
    with _lock:
        return job_id in _cancel_requested


def cancel_check_factory(job_id: str) -> Callable[[], bool]:
    return lambda: is_cancel_requested(job_id)


def kill_container_for_job(job_id: str) -> bool:
    """SIGKILL the job container if still known or discoverable by label."""
    cid = None
    with _lock:
        cid = _container_ids.get(job_id)
    client = None
    try:
        client = docker.from_env()
        if cid:
            try:
                c = client.containers.get(cid)
                c.kill()
                return True
            except Exception:
                pass
        for c in client.containers.list(all=True, filters={"label": f"stellar-x402.job-id={job_id}"}):
            try:
                c.kill()
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
