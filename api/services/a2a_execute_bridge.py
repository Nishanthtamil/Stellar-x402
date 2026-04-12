"""Run the existing /execute/stream pipeline and collect a final JobResult dict."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Response

from api.models.job import JobRequest


async def collect_execute_result(
    request: JobRequest,
    x_stellar_payment_tx: str | None,
    x_payment: str | None,
    payment_signature: str | None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """
    Returns:
      (mode, auth_body, final_job_dict, log_lines)
      mode is ``auth`` when payment is missing (402 body dict), else ``ok``.
    """
    from api.routers.execute import execute_stream

    log_lines: list[str] = []
    final_result: dict[str, Any] | None = None

    stream_response = await execute_stream(
        request=request,
        x_stellar_payment_tx=x_stellar_payment_tx,
        x_payment=x_payment,
        payment_signature=payment_signature,
        response=Response(),
    )

    if isinstance(stream_response, dict):
        return "auth", stream_response, None, []

    async for chunk in stream_response.body_iterator:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        for raw_line in text.splitlines():
            if not raw_line.startswith("data: "):
                continue
            payload = raw_line[6:].strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
                if "job_id" in parsed and "status" in parsed:
                    final_result = parsed
                else:
                    line = parsed.get("line")
                    if line:
                        log_lines.append(line)
            except Exception:
                continue

    return "ok", None, final_result, log_lines
