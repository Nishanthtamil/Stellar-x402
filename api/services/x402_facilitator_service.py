"""Stellar x402 v2 via HTTP facilitator (verify + settle).

Default asset matches @x402/stellar Exact scheme: **USDC** on the configured network,
not native XLM. Legacy authorization remains X-Stellar-Payment-Tx + 0.05 XLM Horizon check.

See: https://developers.stellar.org/docs/build/agentic-payments/x402
"""

from __future__ import annotations

import json
import os
from decimal import ROUND_DOWN, Decimal
from typing import Any

from x402.http import (
    FacilitatorConfig,
    HTTPFacilitatorClient,
)
from x402.http.facilitator_client_base import CreateHeadersAuthProvider
from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo

USDC_TESTNET = "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"
USDC_PUBNET = "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75"


def facilitator_enabled() -> bool:
    v = os.getenv("X402_FACILITATOR_ENABLED", "true").strip().lower()
    return v not in ("0", "false", "no")


def stellar_network_caip2() -> str:
    n = (os.getenv("X402_STELLAR_NETWORK") or os.getenv("STELLAR_NETWORK") or "TESTNET").upper()
    if n in ("PUBLIC", "MAINNET", "PUBNET", "PUBLIC GLOBAL"):
        return "stellar:pubnet"
    return "stellar:testnet"


def _default_usdc_asset(network: str) -> str:
    if network == "stellar:pubnet":
        return (os.getenv("X402_STELLAR_ASSET") or USDC_PUBNET).strip()
    return (os.getenv("X402_STELLAR_ASSET") or USDC_TESTNET).strip()


def decimal_to_smallest_units(amount: str, decimals: int) -> str:
    d = Decimal(amount.strip())
    scale = Decimal(10) ** decimals
    q = (d * scale).quantize(Decimal(1), rounding=ROUND_DOWN)
    return str(int(q))


def build_payment_requirements() -> PaymentRequirements:
    executor = (os.getenv("EXECUTOR_PUBLIC_KEY") or "").strip()
    if not executor:
        raise ValueError("EXECUTOR_PUBLIC_KEY is not set")
    network = stellar_network_caip2()
    asset = _default_usdc_asset(network)
    price = (os.getenv("X402_PRICE") or "0.01").strip()
    decimals = int(os.getenv("X402_ASSET_DECIMALS", "7"))
    amount = decimal_to_smallest_units(price, decimals)
    extra: dict[str, Any] = {}
    if os.getenv("X402_FEE_SPONSORED", "true").strip().lower() in ("1", "true", "yes"):
        extra["areFeesSponsored"] = True
    return PaymentRequirements(
        scheme="exact",
        network=network,
        asset=asset,
        amount=amount,
        pay_to=executor,
        max_timeout_seconds=int(os.getenv("X402_MAX_TIMEOUT_SECONDS", "300")),
        extra=extra,
    )


def build_resource_info() -> ResourceInfo:
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    path = "/execute/stream"
    url = f"{base}{path}" if base else path
    return ResourceInfo(
        url=url,
        description="Pay-per-execution Docker runner (SSE); registry check; signed JobResult.",
        mime_type="text/event-stream",
    )


def build_payment_required_dict() -> dict[str, Any]:
    """CamelCase JSON fragment for HTTP 402 (x402 v2)."""
    req = build_payment_requirements()
    pr = PaymentRequired(
        error="Payment Required",
        resource=build_resource_info(),
        accepts=[req],
    )
    return pr.model_dump(mode="json", by_alias=True)


def facilitator_base_url() -> str:
    return (os.getenv("X402_FACILITATOR_URL") or "https://x402.org/facilitator").rstrip("/")


def _make_http_facilitator_client() -> HTTPFacilitatorClient:
    url = facilitator_base_url()
    api_key = (os.getenv("X402_FACILITATOR_API_KEY") or "").strip()
    if api_key:
        auth = CreateHeadersAuthProvider(
            lambda: {
                "verify": {"Authorization": f"Bearer {api_key}"},
                "settle": {"Authorization": f"Bearer {api_key}"},
                "supported": {"Authorization": f"Bearer {api_key}"},
            }
        )
        return HTTPFacilitatorClient(FacilitatorConfig(url=url, auth_provider=auth))
    return HTTPFacilitatorClient(FacilitatorConfig(url=url))


def requirements_bytes_for_match() -> bytes:
    req = build_payment_requirements()
    payload = req.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def verify_and_settle(payment_header_json: str) -> tuple[bool, str, str | None]:
    """Call facilitator /verify then /settle. Returns (ok, message, onchain_tx_or_none)."""
    raw = (payment_header_json or "").strip()
    if not raw:
        return False, "Empty X-Payment payload", None
    payload_bytes = raw.encode("utf-8")
    req_bytes = requirements_bytes_for_match()
    client = _make_http_facilitator_client()
    try:
        verify = await client.verify_from_bytes(payload_bytes, req_bytes)
        if not verify.is_valid:
            parts = [verify.invalid_reason, verify.invalid_message]
            reason = " · ".join(p for p in parts if p) or "verification failed"
            return False, reason, None
        settle = await client.settle_from_bytes(payload_bytes, req_bytes)
        if not settle.success:
            parts = [settle.error_reason, settle.error_message]
            reason = " · ".join(p for p in parts if p) or "settlement failed"
            return False, reason, None
        tx = (settle.transaction or "").strip() or None
        return True, "Facilitator verify + settle succeeded", tx
    finally:
        await client.aclose()
