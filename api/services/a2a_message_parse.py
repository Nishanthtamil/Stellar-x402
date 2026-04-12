"""Map A2A SendMessage HTTP / JSON-RPC payloads to ``JobRequest``."""

from __future__ import annotations

import json
import os
from typing import Any

from api.models.job import JobRequest


def _merge_dict(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    out.update(b)
    return out


def job_request_from_a2a_send(body: dict[str, Any]) -> JobRequest:
    """
    Accepts ``SendMessageRequest``-shaped JSON (``message`` + optional top-level ``metadata``)
    or HTTP+JSON body as in A2A examples.
    """
    msg = body.get("message") or {}
    meta = body.get("metadata") or {}
    if isinstance(msg.get("metadata"), dict):
        meta = _merge_dict(meta, msg["metadata"])

    parts = msg.get("parts") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and "text" in p and p["text"] is not None:
            texts.append(str(p["text"]))
    blob = "\n".join(t.strip() for t in texts if str(t).strip()).strip()

    if blob.startswith("{") and blob.endswith("}"):
        try:
            inner = json.loads(blob)
            if isinstance(inner, dict):
                meta = _merge_dict(meta, inner.get("metadata") or {})
                if "executor" in inner:
                    meta = _merge_dict(meta, {"executor": inner["executor"]})
                if isinstance(inner.get("input"), dict):
                    meta = _merge_dict(meta, {"input": inner["input"]})
                for k in ("agent_id", "image", "cmd", "task"):
                    if inner.get(k) is not None:
                        meta[k] = inner[k]
        except json.JSONDecodeError:
            pass

    ex = meta.get("executor")
    if not isinstance(ex, dict):
        ex = {}

    default_agent = (os.getenv("AGENT_CARD_AGENT_ID") or "agent_402").strip()
    agent_id = (
        ex.get("agent_id")
        or meta.get("agent_id")
        or default_agent
    )
    if not isinstance(agent_id, str):
        agent_id = str(agent_id)

    image = ex.get("image") or meta.get("image") or "python:3.11-slim"
    cmd = ex.get("cmd") or meta.get("cmd") or ""
    if not isinstance(cmd, str):
        cmd = str(cmd)
    task = ex.get("task") or meta.get("task") or "a2a_send"
    if not isinstance(task, str):
        task = str(task)
    input_obj = ex.get("input") if isinstance(ex.get("input"), dict) else meta.get("input")
    if not isinstance(input_obj, dict):
        input_obj = {}

    if not cmd.strip():
        raise ValueError(
            "Missing container command: set metadata.executor.cmd (or JSON body with cmd / executor.cmd)."
        )

    return JobRequest(
        task=task,
        input=input_obj,
        agent_id=agent_id,
        image=str(image),
        cmd=cmd,
    )
