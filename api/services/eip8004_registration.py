"""Build ERC-8004 `registration-v1` documents for Stellar (Soroban) identity.

ERC-8004 defines EVM-centric `agentRegistry` strings. On Stellar we use the
CAIP-inspired namespace ``stellar`` so verifiers can treat this as a first-class
registration file while still resolving A2A / x402 endpoints.
"""

from __future__ import annotations

import os
from typing import Any

from api.services.discovery_builder import load_local_agent_metadata


def _public_base() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def build_stellar_agent_registry_string() -> str:
    """``stellar:{network}:{registry_contract_id}`` — Soroban registry contract."""
    net = (os.getenv("STELLAR_NETWORK") or "TESTNET").strip().upper()
    cid = (os.getenv("REGISTRY_CONTRACT_ID") or "").strip()
    return f"stellar:{net}:{cid}" if cid else ""


def registration_document_ready() -> bool:
    """Do not publish a registration-v1 document without a real public URL and on-chain registry."""
    return bool(_public_base() and build_stellar_agent_registry_string())


def build_8004_registration_v1() -> dict[str, Any] | None:
    """
    ERC-8004 registration file (off-chain), see:
    https://eips.ethereum.org/EIPS/eip-8004#registration-v1

    Returns ``None`` when ``PUBLIC_BASE_URL`` or ``REGISTRY_CONTRACT_ID`` is unset
    (caller should respond with 503 — no invented URLs or empty ``registrations``).
    """
    if not registration_document_ready():
        return None

    meta = load_local_agent_metadata()
    if "error" in meta:
        meta = {
            "name": "Stellar x402 Executor",
            "description": "Pay-per-execution agent (configure agent_metadata.json).",
        }

    base = _public_base()
    agent_id = (os.getenv("AGENT_CARD_AGENT_ID") or "agent_402").strip()
    reg = build_stellar_agent_registry_string()

    card_url = f"{base}/.well-known/agent-card.json"
    services: list[dict[str, Any]] = [
        {
            "name": "A2A",
            "endpoint": card_url,
            "version": "1.0",
        },
        {
            "name": "web",
            "endpoint": f"{base}/",
        },
        {
            "name": "x402",
            "endpoint": f"{base}/execute/stream",
            "version": "2",
        },
    ]

    registrations = [{"agentId": agent_id, "agentRegistry": reg}]

    out: dict[str, Any] = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": meta.get("name", "Executor Agent"),
        "description": meta.get(
            "description",
            "Stellar-native execution agent with x402 payment and Soroban registry.",
        ),
        "services": services,
        "x402Support": True,
        "active": True,
        "registrations": registrations,
        "supportedTrust": ["reputation", "crypto-economic"],
        "stellar": {
            "network": (os.getenv("STELLAR_NETWORK") or "TESTNET").strip().upper(),
            "registry_contract_id": (os.getenv("REGISTRY_CONTRACT_ID") or "").strip() or None,
            "agent_id": agent_id,
            "note": (
                "On Stellar, `agentId` in `registrations` is the Soroban registry string id "
                "(not an ERC-721 token id). `agentRegistry` points at the Soroban contract."
            ),
        },
    }
    img = meta.get("image")
    if isinstance(img, str) and img.strip():
        out["image"] = img.strip()
    return out
