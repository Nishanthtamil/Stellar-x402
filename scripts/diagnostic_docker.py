import asyncio
import time
from api.services.docker_runner import docker_runner

async def diagnostic():
    print("--- Testing Streaming ---")
    start = time.time()
    async for line in docker_runner.run("python:3.11-slim", "python -u -c 'import time; print(\"first\"); time.sleep(2); print(\"second\")'"):
        print(f"[{time.time() - start:.2f}s] {line}")

    print("\n--- Testing OOM ---")
    async for line in docker_runner.run("python:3.11-slim", "python -c 'print(\"allocating\"); b = bytes(512 * 1024 * 1024)'"):
        print(f"{line}")

if __name__ == "__main__":
    asyncio.run(diagnostic())
