"""Docker required: no mock execution unless ALLOW_DOCKER_SIMULATION is set."""

import pytest

from api.services.docker_runner import DockerRunner


class _UnreachablyClient:
    def ping(self):
        raise OSError("Cannot connect to the Docker daemon")

    def close(self):
        pass


@pytest.mark.asyncio
async def test_no_daemon_fails_without_simulation_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_DOCKER_SIMULATION", raising=False)
    monkeypatch.setattr(
        "api.services.docker_runner.docker.from_env",
        lambda: _UnreachablyClient(),
    )
    lines = []
    async for line in DockerRunner().run("python:3.11-slim", "echo hi"):
        lines.append(line)
    assert any("Docker is required" in line and "[ERROR]" in line for line in lines)
    assert not any("SIMULATION" in line for line in lines)


@pytest.mark.asyncio
async def test_no_daemon_allows_simulation_when_env_set(monkeypatch):
    monkeypatch.setenv("ALLOW_DOCKER_SIMULATION", "true")
    monkeypatch.setattr(
        "api.services.docker_runner.docker.from_env",
        lambda: _UnreachablyClient(),
    )
    lines = []
    async for line in DockerRunner().run("python:3.11-slim", "echo hi"):
        lines.append(line)
    assert any("SIMULATION" in line for line in lines)
    assert any("Mock execution completed" in line for line in lines)
