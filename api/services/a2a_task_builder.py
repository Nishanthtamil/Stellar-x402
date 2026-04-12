"""Build A2A ``Task``-shaped dicts from executor ``JobResult``."""

from __future__ import annotations

from typing import Any

from api.models.job import JobResult, JobStatus


def _state(status: JobStatus) -> str:
    if status == JobStatus.COMPLETED:
        return "TASK_STATE_COMPLETED"
    if status == JobStatus.CANCELED:
        return "TASK_STATE_CANCELED"
    if status == JobStatus.TIMEOUT:
        return "TASK_STATE_FAILED"
    return "TASK_STATE_FAILED"


def task_document_from_job_result(job_id: str, result: JobResult) -> dict[str, Any]:
    return {
        "id": job_id,
        "status": {"state": _state(result.status)},
        "artifacts": [
            {
                "artifactId": f"{job_id[:12]}-stdout",
                "name": "executor-output",
                "description": "Container stdout and validation metadata",
                "parts": [{"text": result.output or ""}],
                "metadata": {
                    "verified": result.verified,
                    "validation_strategy": result.validation_strategy.value
                    if result.validation_strategy
                    else None,
                    "validation_reason": result.validation_reason,
                    "signature": result.signature,
                    "pubkey": result.pubkey,
                    "signed_payload": result.signed_payload,
                    "timestamp": result.timestamp,
                },
            }
        ],
    }
