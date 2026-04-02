import pytest
from api.services.docker_runner import docker_runner
import asyncio

@pytest.mark.asyncio
async def test_docker_runner_simple():
    lines = []
    async for line in docker_runner.run("python:3.11-slim", "python -c 'print(2+2)'"):
        lines.append(line)
    assert "4" in lines

@pytest.mark.asyncio
async def test_docker_runner_timeout():
    lines = []
    # Infinite loop
    async for line in docker_runner.run("python:3.11-slim", "python -c 'import time; [time.sleep(1) for _ in range(100)]'", timeout=2):
        lines.append(line)
    assert any("[TIMEOUT]" in line for line in lines)

@pytest.mark.asyncio
async def test_docker_runner_network_disabled():
    lines = []
    # Attempt to ping google
    async for line in docker_runner.run("python:3.11-slim", "python -c \"import socket; socket.create_connection(('8.8.8.8', 53), timeout=1)\""):
        lines.append(line)
    # The container should fail or timeout on network call
    assert any("[ERROR]" in line or "Temporary failure in name resolution" in line or "Network is unreachable" in line for line in lines)
