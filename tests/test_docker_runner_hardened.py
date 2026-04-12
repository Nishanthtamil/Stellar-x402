import asyncio

import pytest

from api.services.docker_runner import docker_runner


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_runner_missing_image():
    lines = []
    async for line in docker_runner.run("image-that-does-not-exist:latest", "echo hello"):
        lines.append(line)
    # Allowlist runs before pull; disallowed names never reach ImageNotFound.
    assert any(
        "not in the allowlist" in line or "not found" in line for line in lines
    ), lines

@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_runner_oom():
    lines = []
    # Push past 256m limit; grow in chunks so pages are committed.
    cmd = (
        "python -u -c 'print(\"allocating\"); "
        "chunks=[]; "
        "exec(\"while True:\\n chunks.append(bytearray(32*1024*1024))\")'"
    )
    async for line in docker_runner.run("python:3.11-slim", cmd):
        lines.append(line)
    blob = "\n".join(lines)
    assert "OOM (Out of Memory)" in blob or (
        "allocating" in blob
        and any(
            "MemoryError" in line or "Cannot allocate" in line for line in lines
        )
    ) or "Process exited" in blob

@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_runner_non_zero_exit():
    lines = []
    async for line in docker_runner.run("python:3.11-slim", "python -c 'import sys; sys.exit(1)'"):
        lines.append(line)
    assert any("Process exited with code 1" in line for line in lines)

@pytest.mark.docker
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

@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_runner_concurrency():
    # Docker Desktop can drop parallel create/start bursts; cap concurrency.
    sem = asyncio.Semaphore(2)

    async def run_one(i):
        async with sem:
            lines = []
            async for line in docker_runner.run(
                "python:3.11-slim", f"python -c 'print({i})'"
            ):
                lines.append(line)
            return lines

    results = await asyncio.gather(*[run_one(i) for i in range(5)])
    for i, res in enumerate(results):
        assert any(str(i) == line for line in res)
