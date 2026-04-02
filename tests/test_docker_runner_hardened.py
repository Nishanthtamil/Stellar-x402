import pytest
from api.services.docker_runner import docker_runner
import asyncio

@pytest.mark.asyncio
async def test_docker_runner_missing_image():
    lines = []
    async for line in docker_runner.run("image-that-does-not-exist:latest", "echo hello"):
        lines.append(line)
    assert any("Image 'image-that-does-not-exist:latest' not found" in line for line in lines)

@pytest.mark.asyncio
async def test_docker_runner_oom():
    lines = []
    # Trigger OOM. We use a command that definitely exceeds 256MB.
    async for line in docker_runner.run("python:3.11-slim", "python -c 'print(\"allocating\"); b = bytes(512 * 1024 * 1024)'"):
        lines.append(line)
    # The output should contain the OOM error yielded after the loop
    assert any("OOM (Out of Memory)" in line for line in lines)

@pytest.mark.asyncio
async def test_docker_runner_non_zero_exit():
    lines = []
    async for line in docker_runner.run("python:3.11-slim", "python -c 'import sys; sys.exit(1)'"):
        lines.append(line)
    assert any("Process exited with code 1" in line for line in lines)

@pytest.mark.asyncio
async def test_docker_runner_streaming_behavior():
    lines = []
    start_time = asyncio.get_event_loop().time()
    # Use -u for unbuffered output to ensure streaming
    async for line in docker_runner.run("python:3.11-slim", "python -u -c 'import time; print(\"first\"); time.sleep(2); print(\"second\")'"):
        lines.append((line, asyncio.get_event_loop().time() - start_time))
    
    # Extract labels
    labels = [l[0] for l in lines]
    assert "first" in labels
    assert "second" in labels
    
    # Verify 'first' arrived significantly before 'second'
    first_time = next(t for l, t in lines if l == "first")
    second_time = next(t for l, t in lines if l == "second")
    assert second_time - first_time >= 1.5

@pytest.mark.asyncio
async def test_docker_runner_concurrency():
    async def run_one(i):
        lines = []
        async for line in docker_runner.run("python:3.11-slim", f"python -c 'print({i})'"):
            lines.append(line)
        return lines

    # Run 5 tasks concurrently
    results = await asyncio.gather(*[run_one(i) for i in range(5)])
    for i, res in enumerate(results):
        assert any(str(i) == line for line in res)
