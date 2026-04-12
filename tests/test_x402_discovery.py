"""x402 prepare-payment and discovery endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from stellar_sdk import Keypair

from api.main import app

client = TestClient(app)


def test_discovery_includes_x402_block(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    r = client.get("/api/discovery")
    assert r.status_code == 200
    data = r.json()
    assert "error" not in data
    assert data["x402"]["amount_xlm"] == "0.05"
    assert data["x402"]["prepare_unsigned_transaction"] == "http://127.0.0.1:8000/api/x402/prepare-payment"


def test_discovery_prepare_url_none_without_public_base(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    r = client.get("/api/discovery")
    assert r.status_code == 200
    assert r.json()["x402"].get("prepare_unsigned_transaction") is None


def test_prepare_payment_rejects_invalid_source():
    r = client.post(
        "/api/x402/prepare-payment",
        json={"source_public_key": "not-a-stellar-address"},
    )
    assert r.status_code == 400


def test_prepare_payment_requires_executor(monkeypatch):
    monkeypatch.setenv("EXECUTOR_PUBLIC_KEY", "")
    kp = Keypair.random()
    r = client.post(
        "/api/x402/prepare-payment",
        json={"source_public_key": kp.public_key},
    )
    assert r.status_code == 503


@patch("api.services.registry_client.registry_client.get_agent_record", return_value=None)
def test_discovery_resolved_shape(_mock_rec):
    r = client.get("/api/discovery/resolved", params={"agent_id": "agent_402"})
    assert r.status_code == 200
    body = r.json()
    assert "local_file_and_env" in body
    assert "on_chain_agent" in body
    assert "ipfs_metadata" in body
