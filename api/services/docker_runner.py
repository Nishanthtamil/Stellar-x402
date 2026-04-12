import asyncio
import os
import queue
import threading
import time
from typing import AsyncGenerator, Callable

import docker
from docker.errors import APIError, ImageNotFound

_LOG_END = object()
_LOG_NO_CHUNK = object()

# ---------------------------------------------------------------------------
# Image allowlist — only these images can be run as jobs.
# To add more, extend this set or set DOCKER_ALLOWED_IMAGES in .env
# (comma-separated list, e.g. "python:3.11-slim,node:20-slim").
# In dev mode (REGISTRY_BYPASS_DEV=true), the allowlist is still enforced.
# To disable the allowlist entirely (NOT recommended for production),
# set DOCKER_DISABLE_ALLOWLIST=true.
# ---------------------------------------------------------------------------
_DEFAULT_ALLOWED_IMAGES = {
    "python:3.11-slim",
    "python:3.11",
    "python:3.12-slim",
    "python:3.12",
    "node:20-slim",
    "node:20",
    "alpine:latest",
    "alpine:3.19",
    "ubuntu:22.04",
    "ubuntu:24.04",
    "busybox:latest",
    "mcr.microsoft.com/playwright/python:v1.45.0-jammy",
}


def _get_allowed_images() -> set[str]:
    """Returns the set of allowed images from env or defaults."""
    env_val = os.getenv("DOCKER_ALLOWED_IMAGES", "").strip()
    if env_val:
        extras = {img.strip() for img in env_val.split(",") if img.strip()}
        return _DEFAULT_ALLOWED_IMAGES | extras
    return _DEFAULT_ALLOWED_IMAGES


def _allowlist_disabled() -> bool:
    v = os.getenv("DOCKER_DISABLE_ALLOWLIST", "").strip().lower()
    return v in ("1", "true", "yes")


def _image_allowed(image: str) -> bool:
    if _allowlist_disabled():
        return True
    return image.strip() in _get_allowed_images()


def _keep_job_container() -> bool:
    """If true, do not remove the job container after run (easier to see in Docker Desktop). Dev only."""
    v = os.getenv("DOCKER_KEEP_CONTAINERS", "").strip().lower()
    return v in ("1", "true", "yes")


class OpenClawRunner:
    def __init__(self):
        # We don't store a persistent client because it's not thread-safe for many overlapping runs.
        # We only check once if Docker is available to avoid spamming errors if it's down.
        self._initial_check_done = False
        self._docker_available = False
        self._lifecycle_lock = threading.Lock()

    def _check_docker(self) -> bool:
        try:
            client = docker.from_env()
            client.ping()
            client.close()
            return True
        except Exception:
            return False

    async def run(
        self,
        image: str,
        cmd: str,
        timeout: int = 30,
        *,
        env: dict[str, str] | None = None,
        network_enabled: bool = False,
        job_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AsyncGenerator[str, None]:
        # Check image allowlist before doing anything else
        if not _image_allowed(image):
            allowed = sorted(_get_allowed_images())
            yield f"[ERROR] Image '{image}' is not in the allowlist. Allowed images: {', '.join(allowed)}"
            return

        # Try to connect.
        try:
            client = docker.from_env()
            client.ping()  # Verify actual connectivity
        except Exception as e:
            yield f"[ERROR] Docker is required but the daemon is not reachable: {e}"
            return

        container = None
        timed_out = False
        log_q: queue.Queue[object] = queue.Queue()

        def pump_logs(iterator):
            try:
                for chunk in iterator:
                    log_q.put(chunk)
            except Exception as e:
                log_q.put(e)
            finally:
                log_q.put(_LOG_END)

        try:
            labels = {
                "openclaw.executor-job": "true",
                "openclaw.kind": "docker-runner",
            }
            if job_id:
                labels["openclaw.job-id"] = job_id
            with self._lifecycle_lock:
                mem_limit = "256m"
                if network_enabled or "playwright" in image:
                    mem_limit = "512m"

                tmpfs = {
                    "/tmp": "size=256m",
                    "/var/tmp": "size=64m",
                    "/root/.cache": "size=256m",
                }

                container = client.containers.create(
                    image=image,
                    command=cmd,
                    environment=env,
                    network_disabled=not network_enabled,
                    mem_limit=mem_limit,
                    nano_cpus=int(0.5 * 1e9),
                    pids_limit=64,
                    read_only=True,
                    security_opt=["no-new-privileges"],
                    labels=labels,
                    tmpfs=tmpfs,
                )
                container.start()
            if job_id:
                from api.services import docker_job_control as djc

                djc.register_container(job_id, container.id)
            start_time = time.time()

            log_iterator = container.logs(stream=True, follow=True)
            threading.Thread(
                target=pump_logs, args=(log_iterator,), daemon=True
            ).start()

            loop = asyncio.get_event_loop()

            def dequeue() -> object:
                try:
                    return log_q.get(timeout=0.5)
                except queue.Empty:
                    return _LOG_NO_CHUNK

            while True:
                if cancel_check and cancel_check():
                    try:
                        container.kill()
                    except Exception:
                        pass
                    yield "[ERROR] Job canceled by client (OpenClaw)."
                    break
                if time.time() - start_time > timeout:
                    try:
                        container.kill()
                    except Exception:
                        pass
                    timed_out = True
                    yield f"[TIMEOUT] Execution exceeded {timeout}s limit (OpenClaw)."
                    break

                try:
                    item = await asyncio.wait_for(
                        loop.run_in_executor(None, dequeue),
                        timeout=0.6,
                    )
                except asyncio.TimeoutError:
                    continue

                if item is _LOG_NO_CHUNK:
                    continue

                if item is _LOG_END:
                    break
                if isinstance(item, Exception):
                    raise item

                line_bytes = item
                text = line_bytes.decode("utf-8", errors="replace").strip()
                if text:
                    for l in text.splitlines():
                        yield l.strip()

            container.reload()
            state = container.attrs["State"]
            exit_code = state["ExitCode"]
            oom_killed = state.get("OOMKilled", False)

            if timed_out:
                pass
            elif oom_killed or exit_code == 137:
                yield "[ERROR] Container killed due to OOM (OpenClaw)."
            elif exit_code != 0 and not state.get("Running"):
                yield f"[ERROR] Process exited with code {exit_code} (OpenClaw)."

        except ImageNotFound:
            yield f"[ERROR] Image '{image}' not found (OpenClaw)."
        except APIError as e:
            yield f"[ERROR] Docker API error: {str(e)}"
        except Exception as e:
            yield f"[ERROR] Runtime error: {str(e)}"
        finally:
            if job_id:
                from api.services import docker_job_control as djc

                djc.unregister_container(job_id)
            if container and not _keep_job_container():
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass


docker_runner = OpenClawRunner()
