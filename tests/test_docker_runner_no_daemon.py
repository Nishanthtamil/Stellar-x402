"""Docker required: unreachable daemon always fails (no mock execution)."""

import pytest

from api.services.docker_runner import DockerRunner


class _UnreachablyClient:
    def ping(self):
        raise OSError("Cannot connect to the Docker daemon")

    def close(self):
        pass


@pytest.mark.asyncio
async def test_no_daemon_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "api.services.docker_runner.docker.from_env",
        lambda: _UnreachablyClient(),
    )
    lines = []
    async for line in DockerRunner().run("python:3.11-slim", "echo hi"):
        lines.append(line)
    assert any("Docker is required" in line and "[ERROR]" in line for line in lines)
    assert not any("SIMULATION" in line for line in lines)
