"""
A2A v1 HTTP+JSON and JSON-RPC bindings, plus EIP-8004 registration discovery.

- Agent Card: ``GET /.well-known/agent-card.json``
- Registration v1: ``GET /.well-known/agent-registration.json``
- Send message (REST): ``POST /message:send``
- JSON-RPC: ``POST /a2a/jsonrpc`` (``SendMessage``, ``GetTask``, ``ListTasks``, ``CancelTask``)
- Tasks: ``GET /tasks/{id}``, ``GET /tasks``, ``POST /tasks/{task_id}:cancel``,
  ``POST /tasks/{task_id}:subscribe`` (SSE task events)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.services.a2a_agent_card import build_a2a_agent_card
from api.services.a2a_execute_bridge import collect_execute_result
from api.services.a2a_message_parse import job_request_from_a2a_send
from api.services import a2a_persistence
from api.services.eip8004_registration import build_8004_registration_v1


def get_task(task_id: str) -> dict[str, Any] | None:
    return a2a_persistence.get_task(task_id)


def list_tasks(
    *,
    page_size: int = 50,
    status_state: str | None = None,
) -> list[dict[str, Any]]:
    return a2a_persistence.list_tasks(page_size=page_size, status_state=status_state)


def remember_task(task_id: str, document: dict[str, Any]) -> None:
    a2a_persistence.remember_task(task_id, document)

router = APIRouter(tags=["a2a", "eip-8004"])

_A2A_JSON = "application/a2a+json"


def _json_a2a(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status, media_type=_A2A_JSON)


def _job_status_to_a2a_state(status_val: str) -> str:
    m = {
        "completed": "TASK_STATE_COMPLETED",
        "failed": "TASK_STATE_FAILED",
        "timeout": "TASK_STATE_FAILED",
        "canceled": "TASK_STATE_CANCELED",
        "pending": "TASK_STATE_SUBMITTED",
        "running": "TASK_STATE_WORKING",
    }
    return m.get((status_val or "").lower(), "TASK_STATE_FAILED")


def _task_from_job_result(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("job_id"),
        "status": {"state": _job_status_to_a2a_state(str(job.get("status", "failed")))},
        "artifacts": [
            {
                "artifactId": f"{(job.get('job_id') or 'job')[:12]}-stdout",
                "name": "executor-output",
                "description": "Container stdout and validation metadata",
                "parts": [{"text": job.get("output", "")}],
                "metadata": {
                    "verified": job.get("verified"),
                    "validation_strategy": job.get("validation_strategy"),
                    "validation_reason": job.get("validation_reason"),
                    "signature": job.get("signature"),
                    "pubkey": job.get("pubkey"),
                    "signed_payload": job.get("signed_payload"),
                    "timestamp": job.get("timestamp"),
                    "executor_log": job.get("log"),
                },
            }
        ],
    }


def _task_auth_required(task_id: str, payment_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task_id,
        "status": {
            "state": "TASK_STATE_AUTH_REQUIRED",
            "message": "x402 or legacy Stellar payment required before execution.",
        },
        "artifacts": [
            {
                "artifactId": f"{task_id[:12]}-payment",
                "name": "payment-required",
                "parts": [{"text": json.dumps(payment_body)}],
                "metadata": {"contentType": "application/x402+json"},
            }
        ],
    }


async def _run_send_message(
    payload: dict[str, Any],
    x_stellar_payment_tx: str | None,
    x_payment: str | None,
    payment_signature: str | None,
) -> dict[str, Any]:
    job_req = job_request_from_a2a_send(payload)
    mode, auth_body, final_job, _logs = await collect_execute_result(
        job_req,
        x_stellar_payment_tx,
        x_payment,
        payment_signature,
    )

    if mode == "auth" and isinstance(auth_body, dict):
        tid = str(uuid.uuid4())
        doc = _task_auth_required(tid, auth_body)
        remember_task(tid, doc)
        return {"task": doc}

    if not final_job:
        # No durable job id from the executor — do not invent a task record for GetTask polling.
        return {
            "task": {
                "id": None,
                "status": {"state": "TASK_STATE_FAILED"},
                "artifacts": [
                    {
                        "artifactId": "executor-no-result",
                        "name": "executor-error",
                        "parts": [
                            {
                                "text": (
                                    "The executor stream ended without a final job result "
                                    "(payment, registry, or Docker may have failed). Not stored."
                                )
                            }
                        ],
                    }
                ],
            }
        }

    final_job = dict(final_job)
    tid = str(final_job.get("job_id") or uuid.uuid4())
    doc = _task_from_job_result(final_job)
    doc["id"] = tid
    remember_task(tid, doc)
    return {"task": doc}


@router.get("/.well-known/agent-card.json")
async def well_known_agent_card():
    card = build_a2a_agent_card()
    if card is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Agent Card unavailable: set PUBLIC_BASE_URL to your real public origin (no implicit localhost)."
            },
            media_type="application/json",
        )
    return _json_a2a(card)


@router.get("/.well-known/agent-registration.json")
async def well_known_agent_registration():
    doc = build_8004_registration_v1()
    if doc is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "EIP-8004 registration unavailable: set PUBLIC_BASE_URL and REGISTRY_CONTRACT_ID "
                    "(empty registrations are not published)."
                )
            },
            media_type="application/json",
        )
    return _json_a2a(doc)


@router.post("/message:send")
async def http_send_message(
    request: Request,
    x_stellar_payment_tx: str | None = Header(None, alias="X-Stellar-Payment-Tx"),
    x_payment: str | None = Header(None, alias="X-Payment"),
    payment_signature: str | None = Header(None, alias="Payment-Signature"),
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    try:
        out = await _run_send_message(body, x_stellar_payment_tx, x_payment, payment_signature)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _json_a2a(out)


@router.post("/message:stream")
async def http_send_message_stream():
    """Reserved for A2A streaming send; execution uses ``/execute/stream`` plus task subscribe."""
    return _json_a2a(
        {
            "error": {
                "type": "UnsupportedOperationError",
                "message": (
                    "SendStreamingMessage is not implemented. "
                    "Use POST /execute/stream (SSE) for execution, then POST /tasks/{taskId}:subscribe "
                    "for task-scoped events."
                ),
                "domain": "a2a-protocol.org",
            }
        },
        status=501,
    )


@router.get("/tasks/{task_id}")
async def http_get_task(task_id: str):
    doc = get_task(task_id)
    if not doc:
        return _json_a2a(
            {
                "error": {
                    "type": "TaskNotFoundError",
                    "message": f"No task with id {task_id!r}",
                    "domain": "a2a-protocol.org",
                }
            },
            status=404,
        )
    pub = dict(doc)
    pub.pop("_stored_at", None)
    return _json_a2a(pub)


@router.get("/tasks")
async def http_list_tasks(
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(
        None,
        description="Filter by task status.state (e.g. TASK_STATE_WORKING).",
    ),
):
    rows = list_tasks(page_size=page_size, status_state=status)
    tasks = []
    for doc in rows:
        d = dict(doc)
        d.pop("_stored_at", None)
        tasks.append(d)
    n = len(tasks)
    return _json_a2a(
        {"tasks": tasks, "totalSize": n, "pageSize": n, "nextPageToken": ""},
    )


@router.post("/tasks/{task_id}:subscribe")
async def http_subscribe_task(task_id: str):
    """SSE fan-out of executor events for a running job (same payloads as ``/execute/stream`` task channel)."""
    from api.services.execute_broadcast import ensure_channel, subscribe as eb_subscribe

    doc = get_task(task_id)
    if not doc:
        return _json_a2a(
            {
                "error": {
                    "type": "TaskNotFoundError",
                    "message": f"No task with id {task_id!r}",
                    "domain": "a2a-protocol.org",
                }
            },
            status=404,
        )

    await ensure_channel(task_id)
    q = await eb_subscribe(task_id)

    async def events():
        snap = dict(doc)
        snap.pop("_stored_at", None)
        yield f"data: {json.dumps({'snapshot': snap})}\n\n"
        while True:
            item = await q.get()
            if item is None:
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}:cancel")
async def http_cancel_task(task_id: str):
    from api.services import docker_job_control as djc

    doc = get_task(task_id)
    if not doc:
        return _json_a2a(
            {
                "error": {
                    "type": "TaskNotFoundError",
                    "message": f"No task with id {task_id!r}",
                    "domain": "a2a-protocol.org",
                }
            },
            status=404,
        )
    state = (doc.get("status") or {}).get("state", "")
    if state in (
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
    ):
        return _json_a2a(
            {
                "error": {
                    "type": "TaskNotCancelableError",
                    "message": "Task is already in a terminal state.",
                    "domain": "a2a-protocol.org",
                }
            },
            status=409,
        )
    djc.request_cancel(task_id)
    djc.kill_container_for_job(task_id)
    new_doc = dict(doc)
    new_doc["status"] = {
        "state": "TASK_STATE_CANCELED",
        "message": "Cancellation requested; container stop signaled.",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    remember_task(task_id, new_doc)
    pub = dict(new_doc)
    pub.pop("_stored_at", None)
    return _json_a2a({"task": pub})


@router.post("/a2a/jsonrpc")
async def a2a_jsonrpc(
    request: Request,
    x_stellar_payment_tx: str | None = Header(None, alias="X-Stellar-Payment-Tx"),
    x_payment: str | None = Header(None, alias="X-Payment"),
    payment_signature: str | None = Header(None, alias="Payment-Signature"),
):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            media_type="application/json",
            status_code=400,
        )

    if body.get("jsonrpc") != "2.0":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32600, "message": "Invalid Request"},
            },
            media_type="application/json",
            status_code=400,
        )

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "SendMessage":
        try:
            out = await _run_send_message(params, x_stellar_payment_tx, x_payment, payment_signature)
        except ValueError as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": str(e)},
                },
                media_type="application/json",
                status_code=400,
            )
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": out}, media_type="application/json")

    if method == "GetTask":
        tid = (params.get("id") or "").strip()
        if not tid:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing params.id"},
                },
                media_type="application/json",
                status_code=400,
            )
        doc = get_task(tid)
        if not doc:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32001, "message": "Task not found"},
                },
                media_type="application/json",
                status_code=404,
            )
        pub = dict(doc)
        pub.pop("_stored_at", None)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"task": pub}}, media_type="application/json")

    if method == "ListTasks":
        try:
            page_size = int(params.get("pageSize") or params.get("page_size") or 50)
        except (TypeError, ValueError):
            page_size = 50
        page_size = max(1, min(page_size, 200))
        status_filter = params.get("status") or params.get("statusState")
        rows = list_tasks(page_size=page_size, status_state=status_filter)
        tasks = []
        for doc in rows:
            d = dict(doc)
            d.pop("_stored_at", None)
            tasks.append(d)
        n = len(tasks)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tasks": tasks, "totalSize": n, "pageSize": n, "nextPageToken": ""},
            },
            media_type="application/json",
        )

    if method == "CancelTask":
        from api.services import docker_job_control as djc

        tid = (params.get("id") or "").strip()
        if not tid:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing params.id"},
                },
                media_type="application/json",
                status_code=400,
            )
        doc = get_task(tid)
        if not doc:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "Task not found"}},
                media_type="application/json",
                status_code=404,
            )
        state = (doc.get("status") or {}).get("state", "")
        if state in (
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        ):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": "Task not cancelable"},
                },
                media_type="application/json",
                status_code=409,
            )
        djc.request_cancel(tid)
        djc.kill_container_for_job(tid)
        new_doc = dict(doc)
        new_doc["status"] = {
            "state": "TASK_STATE_CANCELED",
            "message": "Cancellation requested; container stop signaled.",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        remember_task(tid, new_doc)
        pub = dict(new_doc)
        pub.pop("_stored_at", None)
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "result": {"task": pub}},
            media_type="application/json",
        )

    if method in ("SendStreamingMessage", "SubscribeToTask"):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": (
                        f"{method} is not implemented over JSON-RPC. "
                        "Use POST /execute/stream and POST /tasks/{{taskId}}:subscribe (SSE)."
                    ),
                },
            },
            media_type="application/json",
            status_code=400,
        )

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method!r}"},
        },
        media_type="application/json",
        status_code=400,
    )


@router.get("/extendedAgentCard")
async def extended_agent_card():
    return _json_a2a(
        {
            "error": {
                "type": "ExtendedAgentCardNotConfiguredError",
                "message": "Extended agent card is not enabled (capabilities.extendedAgentCard is false).",
                "domain": "a2a-protocol.org",
            }
        },
        status=400,
    )
