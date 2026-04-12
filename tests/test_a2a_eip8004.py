"""EIP-8004 registration file + A2A Agent Card + HTTP bindings."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.a2a_agent_card import build_a2a_agent_card
from api.services.a2a_message_parse import job_request_from_a2a_send
from api.services.eip8004_registration import build_8004_registration_v1

client = TestClient(app)


@pytest.fixture
def public_executor_identity(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv(
        "REGISTRY_CONTRACT_ID",
        "CDMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCKMOCK",
    )


def test_agent_card_required_fields(public_executor_identity):
    card = build_a2a_agent_card()
    assert card is not None
    assert card["name"]
    assert card["description"]
    assert card["version"]
    assert isinstance(card["supportedInterfaces"], list) and card["supportedInterfaces"]
    for iface in card["supportedInterfaces"]:
        assert iface.get("url")
        assert iface.get("protocolBinding")
        assert iface.get("protocolVersion")
    assert "capabilities" in card
    assert card["defaultInputModes"]
    assert card["defaultOutputModes"]
    assert card["skills"] and card["skills"][0].get("id")


def test_8004_registration_type_and_services(public_executor_identity):
    reg = build_8004_registration_v1()
    assert reg is not None
    assert reg["type"] == "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    assert reg["name"]
    assert reg["x402Support"] is True
    assert isinstance(reg["services"], list)
    names = {s.get("name") for s in reg["services"]}
    assert "A2A" in names and "web" in names


def test_well_known_agent_card_http(public_executor_identity):
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    data = r.json()
    assert data["name"]
    assert "supportedInterfaces" in data


def test_well_known_agent_registration_http(public_executor_identity):
    r = client.get("/.well-known/agent-registration.json")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"


def test_a2a_parse_send_message_metadata():
    body = {
        "message": {
            "role": "ROLE_USER",
            "parts": [{"text": "ping"}],
            "messageId": "m1",
        },
        "metadata": {
            "executor": {
                "agent_id": "agent_402",
                "image": "python:3.11-slim",
                "cmd": "python -c \"print(1)\"",
                "task": "t",
            }
        },
    }
    jr = job_request_from_a2a_send(body)
    assert jr.agent_id == "agent_402"
    assert jr.cmd.startswith("python")
    assert jr.image == "python:3.11-slim"


def test_jsonrpc_method_not_found():
    r = client.post(
        "/a2a/jsonrpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "Unknown", "params": {}},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32601


@pytest.mark.parametrize(
    "path",
    ["/.well-known/agent-card.json", "/.well-known/agent-registration.json"],
)
def test_well_known_content_type(path, public_executor_identity):
    r = client.get(path)
    assert "json" in (r.headers.get("content-type") or "").lower()


def test_well_known_agent_card_503_without_public_base(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 503


def test_well_known_registration_503_without_registry(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("REGISTRY_CONTRACT_ID", "")
    r = client.get("/.well-known/agent-registration.json")
    assert r.status_code == 503


def test_build_8004_returns_none_when_not_ready(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("REGISTRY_CONTRACT_ID", raising=False)
    assert build_8004_registration_v1() is None
