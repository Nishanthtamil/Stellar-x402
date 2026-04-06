"""POST /execute/stream 402 response shape."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.fixture
def job_body():
    return {
        "task": "demo",
        "input": {},
        "agent_id": "agent_402",
        "cmd": "echo hi",
    }


def test_execute_stream_402_includes_x402_v2(monkeypatch, job_body):
    monkeypatch.setenv("EXECUTOR_PUBLIC_KEY", "GCCNOHVSMCGE62GGT7FEGSRICTNRFOEOJKAOQPUNORGBRNJLR4USNGDF")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    r = client.post("/execute/stream", json=job_body)
    assert r.status_code == 402
    data = r.json()
    assert data.get("x402Version") == 2
    assert data.get("accepts")
    assert data.get("legacy", {}).get("header") == "X-Stellar-Payment-Tx"
    assert "facilitator" in data


@patch("api.routers.execute.x402_facilitator_service.facilitator_enabled", return_value=False)
def test_execute_stream_402_without_facilitator_block(_mock, monkeypatch, job_body):
    monkeypatch.setenv("EXECUTOR_PUBLIC_KEY", "GCCNOHVSMCGE62GGT7FEGSRICTNRFOEOJKAOQPUNORGBRNJLR4USNGDF")
    r = client.post("/execute/stream", json=job_body)
    assert r.status_code == 402
    data = r.json()
    assert "x402Version" not in data
    assert data.get("legacy")
