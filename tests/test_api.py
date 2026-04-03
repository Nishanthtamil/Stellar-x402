import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.mark.docker
def test_execute_stream_endpoint(monkeypatch):
    """x402 requires a payment header; bypass on-chain verify and registry for the test."""
    monkeypatch.setattr(
        "api.routers.execute._verify_payment",
        AsyncMock(return_value=True),
    )
    mock_rc = MagicMock()
    mock_rc.contract_id = None
    mock_rc.get_agent.return_value = None
    mock_rc.update_reputation.return_value = None
    monkeypatch.setattr("api.routers.execute.registry_client", mock_rc)

    payload = {
        "task": "test-task",
        "input": {"expected_substring": "hello-world"},
        "agent_id": "test-agent",
        "cmd": "python -c 'print(\"hello-world\")'",
    }
    headers = {"X-Stellar-Payment-Tx": "0" * 64}

    with client.stream("POST", "/execute/stream", json=payload, headers=headers) as response:
        assert response.status_code == 200
        lines = []
        for raw in response.iter_lines():
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if line.startswith("data: "):
                data = json.loads(line[6:])
                lines.append(data)

        assert any("hello-world" in str(l.get("line")) for l in lines if "line" in l)
        final_result = next(l for l in lines if "status" in l)
        assert final_result["status"] == "completed"
        assert final_result["verified"] is True
        assert final_result["validation_strategy"] == "rule_based"
        assert final_result["signature"]
        assert final_result["pubkey"]
        assert final_result["signed_payload"]["agent_id"] == "test-agent"
