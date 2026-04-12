import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

@pytest.mark.docker
def test_secrets_passed_to_docker(monkeypatch):
    """Verify that secrets are passed as environment variables to the Docker container."""
    monkeypatch.setenv("REGISTRY_BYPASS_DEV", "true")
    monkeypatch.setattr(
        "api.routers.execute._verify_payment",
        AsyncMock(return_value=True),
    )
    mock_rc = MagicMock()
    mock_rc.contract_id = None
    mock_rc.get_agent_record.return_value = None
    mock_rc.update_reputation.return_value = None
    monkeypatch.setattr("api.routers.execute.registry_client", mock_rc)

    payload = {
        "task": "check-env",
        "input": {"expected_substring": "MY_SECRET_VALUE"},
        "agent_id": "test-agent",
        "cmd": "sh -c 'echo $MY_SECRET_KEY'",
        "secrets": {"MY_SECRET_KEY": "MY_SECRET_VALUE"}
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

        # Check that the secret value appeared in the output (since we echoed it)
        assert any("MY_SECRET_VALUE" in str(l.get("line")) for l in lines if "line" in l)
        
        # Verify it completed successfully
        final_result = next(l for l in lines if "status" in l)
        assert final_result["status"] == "completed"
        assert final_result["verified"] is True
        
        # Verify that secrets were stripped from signed_payload and final result
        assert "secrets" not in final_result["signed_payload"]

@pytest.mark.docker
def test_network_enabled_passed_to_docker(monkeypatch):
    """Verify that network_enabled=True is passed to the Docker runner (by testing internet access)."""
    monkeypatch.setenv("REGISTRY_BYPASS_DEV", "true")
    monkeypatch.setattr(
        "api.routers.execute._verify_payment",
        AsyncMock(return_value=True),
    )
    mock_rc = MagicMock()
    mock_rc.contract_id = None
    mock_rc.get_agent_record.return_value = None
    mock_rc.update_reputation.return_value = None
    monkeypatch.setattr("api.routers.execute.registry_client", mock_rc)

    # Note: This test requires the host to have internet and Docker to allow it.
    # We use python:3.11-slim since it's already pulled.
    payload = {
        "task": "check-network",
        "input": {"expected_substring": "doctype html"},
        "agent_id": "test-agent",
        "image": "python:3.11-slim",
        "cmd": "python -c \"import urllib.request; print(urllib.request.urlopen('http://google.com').read()[:50])\"",
        "network_enabled": True
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

        # If network works, we should get HTML doctype
        if not any("doctype html" in str(l.get("line")) for l in lines if "line" in l):
            print(f"DEBUG: Output lines: {lines}")
        
        assert any("doctype html" in str(l.get("line")) for l in lines if "line" in l)
        
        final_result = next(l for l in lines if "status" in l)
        assert final_result["status"] == "completed"
        assert final_result["verified"] is True
