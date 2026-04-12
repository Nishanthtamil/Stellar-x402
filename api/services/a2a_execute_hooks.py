"""Persist A2A task snapshots during ``/execute/stream`` and tear down broadcast channels."""

from __future__ import annotations

from datetime import UTC, datetime

from api.models.job import JobRequest

_WORKING = "TASK_STATE_WORKING"


def _working_doc(job_id: str, request: JobRequest) -> dict:
    return {
        "id": job_id,
        "contextId": None,
        "status": {
            "state": _WORKING,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "history": [],
        "metadata": {
            "executor": {
                "agent_id": request.agent_id,
                "image": request.image,
                "task": request.task,
            }
        },
    }


async def on_job_running(job_id: str, request: JobRequest) -> None:
    from api.services import a2a_persistence
    from api.services.execute_broadcast import ensure_channel

    await ensure_channel(job_id)
    a2a_persistence.remember_task(job_id, _working_doc(job_id, request))


async def on_job_terminal_a2a(job_id: str, task_document: dict) -> None:
    from api.services import a2a_persistence

    a2a_persistence.remember_task(job_id, task_document)


async def on_job_cleanup(job_id: str) -> None:
    from api.services.docker_job_control import clear_cancel
    from api.services.execute_broadcast import close_subscribers

    clear_cancel(job_id)
    await close_subscribers(job_id)
