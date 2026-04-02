import pytest
from fastapi.testclient import TestClient
from api.main import app
import json

client = TestClient(app)

def test_execute_stream_endpoint():
    payload = {
        "task": "test-task",
        "input": {},
        "agent_id": "test-agent",
        "cmd": "python -c 'print(\"hello-world\")'"
    }
    
    with client.stream("POST", "/execute/stream", json=payload) as response:
        assert response.status_code == 200
        lines = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                lines.append(data)
        
        # Check for output line
        assert any("hello-world" in str(l.get("line")) for l in lines if "line" in l)
        # Check for final result
        assert any(l.get("status") == "completed" for l in lines if "status" in l)
