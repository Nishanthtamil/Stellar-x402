"""A2A v1 Agent Card (https://a2a-protocol.org/) for this executor."""

from __future__ import annotations

import os
from typing import Any

from api.services.discovery_builder import load_local_agent_metadata


def agent_card_ready() -> bool:
    """Agent Card URLs must be absolute; do not invent a host."""
    return bool((os.getenv("PUBLIC_BASE_URL") or "").strip())


def build_a2a_agent_card() -> dict[str, Any] | None:
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None

    meta = load_local_agent_metadata()
    if "error" in meta:
        meta = {
            "name": "OpenClaw Executor",
            "description": "OpenClaw-compatible pay-per-execution agent infrastructure.",
        }

    return {
        "name": meta.get("name", "OpenClaw Executor"),
        "description": meta.get(
            "description",
            "Sandboxed OpenClaw Docker execution on Stellar with x402 (USDC / legacy XLM) and on-chain registry.",
        ),
        "version": str(meta.get("version", "1.0.0")),
        "documentationUrl": f"{base}/docs",
        "supportedInterfaces": [
            {
                "url": base,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            },
            {
                "url": f"{base}/a2a/jsonrpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            },
        ],
        "provider": {
            "organization": os.getenv("AGENT_PROVIDER_ORG", "OpenClaw Foundation"),
            "url": os.getenv("AGENT_PROVIDER_URL", "https://developers.stellar.org/docs/build/agentic-payments/x402"),
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": False,
            "openclaw_compatible": True,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "openclaw_execution",
                "name": "OpenClaw Docker execution",
                "description": (
                    "Run a containerized command using the OpenClaw executor after x402 / registry checks. "
                    "Pass Stellar payment headers on the HTTP request. "
                    "Send `metadata.executor` with `image`, `cmd`, `agent_id`, optional `task` and `input`, "
                    "or send a JSON object as the first text part."
                ),
                "tags": ["openclaw", "docker", "x402", "stellar", "soroban", "compute"],
                "examples": [
                    '{"metadata":{"executor":{"agent_id":"agent_402","image":"python:3.11-slim","cmd":"python -c \\"print(1+1)\\""}}}',
                ],
                "inputModes": ["application/json", "text/plain"],
                "outputModes": ["application/json", "text/plain"],
            }
        ],
    }
