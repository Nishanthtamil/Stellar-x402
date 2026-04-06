import asyncio
import os
import queue
import threading
import time
from typing import AsyncGenerator

import docker
from docker.errors import APIError, ImageNotFound

_LOG_END = object()
_LOG_NO_CHUNK = object()


def _simulation_allowed() -> bool:
    v = os.getenv("ALLOW_DOCKER_SIMULATION", "").strip().lower()
    return v in ("1", "true", "yes")


def _keep_job_container() -> bool:
    """If true, do not remove the job container after run (easier to see in Docker Desktop). Dev only."""
    v = os.getenv("DOCKER_KEEP_CONTAINERS", "").strip().lower()
    return v in ("1", "true", "yes")


class DockerRunner:
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

    async def run(self, image: str, cmd: str, timeout: int = 30) -> AsyncGenerator[str, None]:
        # Try to connect.
        try:
            client = docker.from_env()
            client.ping() # Verify actual connectivity
        except Exception as e:
            if _simulation_allowed():
                yield f"[WARN] Docker daemon not available: {e}"
                yield "> [SIMULATION] Entering mock execution environment..."
                await asyncio.sleep(1)
                yield f"> [SIMULATION] Running command: {cmd}"
                await asyncio.sleep(2)
                yield "SUCCESS: Mock execution completed."
                return
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
            with self._lifecycle_lock:
                container = client.containers.create(
                    image=image,
                    command=cmd,
                    network_disabled=True,
                    mem_limit="256m",
                    nano_cpus=int(0.5 * 1e9),
                    pids_limit=64,
                    read_only=True,
                    security_opt=["no-new-privileges"],
                    labels={
                        "stellar-x402.executor-job": "true",
                        "stellar-x402.kind": "docker-runner",
                    },
                )
                container.start()
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
                if time.time() - start_time > timeout:
                    try:
                        container.kill()
                    except Exception:
                        pass
                    timed_out = True
                    yield f"[TIMEOUT] Execution exceeded {timeout}s limit."
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
                yield "[ERROR] Container killed due to OOM (Out of Memory)."
            elif exit_code != 0 and not state.get("Running"):
                yield f"[ERROR] Process exited with code {exit_code}."

        except ImageNotFound:
            yield f"[ERROR] Image '{image}' not found."
        except APIError as e:
            yield f"[ERROR] Docker API error: {str(e)}"
        except Exception as e:
            yield f"[ERROR] Runtime error: {str(e)}"
        finally:
            if container and not _keep_job_container():
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass


docker_runner = DockerRunner()
