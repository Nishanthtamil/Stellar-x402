import docker
import asyncio
import time
from typing import AsyncGenerator
from docker.errors import ImageNotFound, APIError

class DockerRunner:
    def __init__(self):
        try:
            self.client = docker.from_env()
        except Exception as e:
            print(f"Failed to connect to Docker daemon: {e}")
            self.client = None

    async def run(self, image: str, cmd: str, timeout: int = 30) -> AsyncGenerator[str, None]:
        if not self.client:
            yield "[ERROR] Docker daemon not available."
            return

        container = None
        try:
            container = self.client.containers.create(
                image=image,
                command=cmd,
                network_disabled=True,
                mem_limit="256m",
                nano_cpus=int(0.5 * 1e9),
                pids_limit=64,
                read_only=True,
                security_opt=["no-new-privileges"],
            )

            container.start()
            start_time = time.time()

            # Using logs(stream=True) is generally reliable if handled without buffering
            log_iterator = container.logs(stream=True, follow=True)

            loop = asyncio.get_event_loop()
            
            def fetch_next(it):
                try:
                    return next(it)
                except StopIteration:
                    return None

            while True:
                # Check for timeout
                if time.time() - start_time > timeout:
                    try:
                        container.kill()
                    except:
                        pass
                    yield f"[TIMEOUT] Execution exceeded {timeout}s limit."
                    break

                # Non-blocking fetch
                line_bytes = await loop.run_in_executor(None, fetch_next, log_iterator)
                if line_bytes is None:
                    break
                
                text = line_bytes.decode("utf-8", errors="replace").strip()
                if text:
                    for l in text.splitlines():
                        yield l.strip()

            # Final status check - THIS IS CRITICAL FOR OOM
            container.reload()
            state = container.attrs['State']
            exit_code = state['ExitCode']
            oom_killed = state.get('OOMKilled', False)

            if oom_killed:
                yield "[ERROR] Container killed due to OOM (Out of Memory)."
            elif exit_code != 0 and exit_code != 137 and not state.get('Running'):
                yield f"[ERROR] Process exited with code {exit_code}."

        except ImageNotFound:
            yield f"[ERROR] Image '{image}' not found."
        except APIError as e:
            yield f"[ERROR] Docker API error: {str(e)}"
        except Exception as e:
            yield f"[ERROR] Runtime error: {str(e)}"
        finally:
            if container:
                try:
                    container.remove(force=True)
                except:
                    pass

docker_runner = DockerRunner()
