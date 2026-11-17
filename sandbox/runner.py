
import docker
import io
import tarfile
from docker.errors import ImageNotFound
from schemas.sandbox import SandboxConfig, ExecutionResult
from typing import Optional
from .import_guard import ImportGuard
from pathlib import Path
import subprocess
import traceback
import logging
import asyncio
import json
import select
import time


def _extract_frames(buffer: bytearray):
    frames = []

    while len(buffer) >= 8:
        stream_id = buffer[0]
        length = int.from_bytes(buffer[4:8], "big")

        if len(buffer) < 8 + length:
            break

        payload = bytes(buffer[8:8 + length])
        del buffer[:8 + length]

        frames.append((stream_id, payload))

    return frames



class DockerRunner:
    def __init__(self, config: SandboxConfig, mcp_manager=None) -> None:
        """Store configuration and initialize the Docker client."""
        self.config = config
        self.client = docker.from_env()
        self.image = "agent-sandbox:latest"  # DEBUG: verify /testbed/main.py exists in mounted volume
        self.testbed_volume = self.client.volumes.create(
            name=f"agent-testbed"
        )
        self.agent_volume = self.client.volumes.create(
            name=f"agent-tmp"
        )

        self.import_guard = ImportGuard(
            config.authorized_imports
        )
        self._ensure_image()
        self._initialize_volumes()
        self.mcp_manager = mcp_manager

    def _ensure_image(self) -> None:
        """Build the Docker image from the local Dockerfile if missing."""

        try:
            self.client.images.get(self.image)
            print(f"Image {self.image} already exists.")
            return

        except ImageNotFound:
            print("Building sandbox image...")

            context = Path(__file__).resolve().parent
            repository_root = context.parent

            subprocess.run(
                [
                    "docker", "build",
                    "-t", self.image,
                    "-f", str(context / "Dockerfile"),
                    str(repository_root),
                ],
                check=True,
            )

            print("Image built successfully.")


    def _initialize_volumes(self) -> None:
        """Set volume ownership to the non-root sandbox user."""
        init = self.client.containers.create(
            image=self.image,
            command=[
                "sh", "-c",
                "chown -R 65534:65534 /testbed /tmp/agent"
            ],
            user="0:0",
            volumes={
                self.testbed_volume.name: {
                    "bind": "/testbed",
                    "mode": "rw",
                },
                self.agent_volume.name: {
                    "bind": "/tmp/agent",
                    "mode": "rw",
                },
            },
        )

        try:
            init.start()
            result = init.wait(timeout=10)

            if result["StatusCode"] != 0:
                raise RuntimeError(
                    "Failed to initialize sandbox volume permissions"
                )
        finally:
            init.remove(force=True)

    def _handle_execution_timeout(self, container) -> ExecutionResult:
        """Stop an execution that exceeded its configured wall-clock deadline."""
        try:
            container.kill()
        except docker.errors.NotFound:
            pass
        except docker.errors.DockerException as exc:
            logging.warning("Could not kill timed-out container: %s", exc)

        return ExecutionResult(
            error="Execution timed out.",
            timed_out=True,
        )

    def _wait_for_execution(self, container) -> dict:
        """Poll container state against a real monotonic deadline.

        Docker's container.wait(timeout=...) sets an HTTP request timeout;
        it is not itself a reliable execution timer.
        """
        deadline = time.monotonic() + self.config.max_execution_time_seconds
        while True:
            container.reload()
            state = container.attrs["State"]
            if not state.get("Running", False):
                return {"StatusCode": state.get("ExitCode", 1)}
            if time.monotonic() >= deadline:
                raise TimeoutError("Sandbox execution deadline exceeded")
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _handle_memory_limit(self, container) -> Optional[ExecutionResult]:
        """Check whether the container exceeded its memory limit."""
        try:
            container.reload()
            state = container.attrs["State"]

            if state.get("OOMKilled", False):
                return ExecutionResult(
                    error=(
                        f"Execution exceeded the memory limit "
                        f"({self.config.max_memory_mb} MB)."
                    ),
                    resource_limit_exceeded=True,
                )

        except docker.errors.DockerException as exc:
            raise RuntimeError(
                f"Failed to inspect container state: {exc}"
            ) from exc

        return None

    def _collect_output(self, container) -> tuple[str, str, bool]:
        """Collect stdout/stderr from the container and apply byte limits."""
        stdout = container.logs(stdout=True, stderr=False, stream=False)
        stderr = container.logs(stdout=False, stderr=True, stream=False)
        stdout = stdout or b""
        stderr = stderr or b""
        max_bytes = self.config.max_output_bytes

        truncated = False

        if len(stdout) + len(stderr) > max_bytes:
            truncated = True

            # Allocate half of the available output to each stream.
            stdout_limit = max_bytes // 2
            stderr_limit = max_bytes - stdout_limit

            stdout = stdout[:stdout_limit]
            stderr = stderr[:stderr_limit]

        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            truncated,
        )

    def _build_container_config(self) -> dict:
        """Build Docker container settings."""

        
        return {
            "image": self.image,
            "command": ["python", "/testbed/main.py"],
            "working_dir": "/testbed",
            "network_mode": "none",
            "stdin_open": True,
            "tty": False,
            "detach": True,
            # Privilege restrictions
            "user": "65534:65534",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            # Filesystem restrictions
            "read_only": True,
            "volumes": {
                f"{self.testbed_volume.name}": {
                    "bind": "/testbed",
                    "mode": "rw",
                },
                f"{self.agent_volume.name}": {
                    "bind": "/tmp/agent",
                    "mode": "rw",
                },
            },
            # Resource restrictions
            # "nano_cpus": int(self.config.max_cpu_cores * 1_000_000_000),
            "pids_limit": self.config.max_processes,
            "mem_limit": f"{self.config.max_memory_mb}m",
            # "storage_opt": {
            #     "size": f"{self.config.max_disk_usage_mb}m"
            # },

        }

    def _read_final_answer(self, container) -> dict:
        """Read the final answer result from the Docker container."""

        archive, _ = container.get_archive("/tmp/agent/result.json")

        with tarfile.open(fileobj=io.BytesIO(b"".join(archive)), mode="r:*") as tar:
            file = tar.extractfile("result.json")

            if file is None:
                raise FileNotFoundError("result.json not found in Docker archive")

            return json.load(file)

    def _close_attachment(self, connection):
        """Close a Docker socket attachment."""
        if connection is None:
            return

        response = getattr(connection, "_response", None)

        try:
            if response is not None:
                response.close()
        finally:
            connection.close()

    def _debug_container(self, container) -> None:
        """Best-effort diagnostics without masking the original error."""
        if container is None:
            return
        print(f"[DEBUG] Container ID: {container.id}", flush=True)
        try:
            container.reload()
            print("[DEBUG] State:", container.attrs.get("State"), flush=True)
            print("[DEBUG] Image:", container.attrs.get("Config", {}).get("Image"), flush=True)
            print("[DEBUG] Command:", container.attrs.get("Config", {}).get("Cmd"), flush=True)
        except docker.errors.DockerException as exc:
            print("[DEBUG] Inspect failed:", repr(exc), flush=True)
        try:
            out = container.logs(stdout=True, stderr=False)
            err = container.logs(stdout=False, stderr=True)
            print("[DEBUG] STDOUT:", (out or b"").decode(errors="replace")[-4000:], flush=True)
            print("[DEBUG] STDERR:", (err or b"").decode(errors="replace")[-4000:], flush=True)
        except docker.errors.DockerException as exc:
            print("[DEBUG] Logs failed:", repr(exc), flush=True)


    async def _dispatch_tool_request(self, request: dict) -> dict:
        request_id = request["id"]

        try:
            if self.mcp_manager is None:
                raise RuntimeError("MCP manager not configured")

            tool_name = request["name"]
            arguments = request.get("arguments", {})

            # 1. Execute the MCP tool
            result = await self.mcp_manager.call_tool(
                tool_name,
                arguments,
            )

            # 2. Check whether MCP reported an error
            if result.isError:
                error_text = "\n".join(
                    item.text
                    for item in result.content
                    if item.type == "text"
                )
                raise RuntimeError(error_text or "MCP tool reported an error")

            # 3. Extract text from the MCP response
            texts = [
                item.text
                for item in result.content
                if item.type == "text"
            ]

            tool_result = "\n".join(texts)

            # 4. Send the extracted result back to the container
            return {
                "type": "tool_result",
                "id": request_id,
                "success": True,
                "result": tool_result,
            }

        except Exception as exc:
            return {
                "type": "tool_result",
                "id": request_id,
                "success": False,
                "error": str(exc),
            }



    async def _process_ipc(
        self,
        container,
        connection,
        deadline,
        allowed_tools,
    ):
        sock = connection._sock
        frame_buffer = bytearray()
        stdout_buffer = bytearray()

        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Sandbox execution timed out")

            readable, _, _ = await asyncio.to_thread(
                select.select, [sock], [], [], 0.1
            )

            if readable:
                data = await asyncio.to_thread(sock.recv, 65536)

                if not data:
                    # Socket closed: retrieve the container exit status.
                    await asyncio.to_thread(container.reload)
                    state = container.attrs["State"]

                    if state["Running"]:
                        raise RuntimeError(
                            "IPC socket closed while container is running"
                        )

                    if frame_buffer or stdout_buffer:
                        raise RuntimeError(
                            "IPC socket closed with incomplete message"
                        )

                    return {"StatusCode": state["ExitCode"]}

                frame_buffer.extend(data)

                for stream_id, payload in _extract_frames(frame_buffer):
                    if stream_id != 1:
                        continue

                    stdout_buffer.extend(payload)

                    while b"\n" in stdout_buffer:
                        line, _, remaining = stdout_buffer.partition(b"\n")
                        stdout_buffer = bytearray(remaining)

                        if not line:
                            continue

                        request = json.loads(line.decode("utf-8"))

                        if request.get("type") != "tool_call":
                            raise RuntimeError("Unexpected IPC message")

                        if request.get("name") not in allowed_tools:
                            raise RuntimeError("Unauthorized MCP tool")

                        remaining_time = deadline - time.monotonic()

                        if remaining_time <= 0:
                            raise TimeoutError(
                                "Sandbox execution timed out"
                            )

                        response = await asyncio.wait_for(
                            self._dispatch_tool_request(request),
                            timeout=remaining_time,
                        )

                        message = (
                            json.dumps(response) + "\n"
                        ).encode("utf-8")

                        await asyncio.to_thread(
                            sock.sendall,
                            message,
                        )

            # Refresh container state.
            await asyncio.to_thread(container.reload)
            container_state = container.attrs["State"]

            # Do not return immediately after the container exits.
            # Continue reading until the socket reaches EOF.
            if not container_state["Running"]:
                continue


    async def run(
        self,
        code: str,
        discovered_tool_names: list[str] | None = None,
    ) -> ExecutionResult:
        """Execute code in an isolated container and return the result."""

        container = None
        connection = None

        try:
            # 1. Validate authorized imports
            self.import_guard.validate(code)

            # 2. Create Docker container
            container = self.client.containers.create(
                **self._build_container_config()
            )

            print("[DEBUG] Created container:", container.short_id, flush=True)
            # 3. Attach to stdin before starting
            connection = container.attach_socket(
                params={
                    "stdin": 1,
                    "stdout": 1,
                    "stream": 1,
                }
            )

            # 4. Start container
            container.start()
            print("[DEBUG] Container started", flush=True)

            # 5. Send code as one JSON line and MCP tools
            message = json.dumps({
                "code": code,
                "tools": discovered_tool_names or [],
            }) + "\n"

            connection._sock.sendall(
                message.encode("utf-8")
            )

            print("[DEBUG] Sent JSON line:", len(message), "characters", flush=True)

            # No shutdown(1) needed.
            # The container reads until newline.

            # 6. Enforce the execution deadline.
            # try:
            #     print("[DEBUG] Waiting for container to exit...", flush=True)
            #     result = self._wait_for_execution(container)
            #     print("[DEBUG] Exit status:", result, flush=True)
            # except TimeoutError:
            #     return self._handle_execution_timeout(container)
            try:
                deadline = (
                    time.monotonic()
                    + self.config.max_execution_time_seconds
                )

                result = await self._process_ipc(
                    container,
                    connection,
                    deadline,
                    set(discovered_tool_names or []),
                )

            except TimeoutError:
                return self._handle_execution_timeout(container)

            # 7. Check memory restriction
            memory_error = self._handle_memory_limit(container)

            if memory_error:
                return memory_error

            # 8. Collect stdout and stderr
            stdout, stderr, truncated = self._collect_output(
                container
            )

            # 9. Handle nonzero exit code
            exit_code = result["StatusCode"]

            if exit_code != 0:
                return ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    truncated=truncated,
                    error=(
                        f"Container exited with code {exit_code}."
                    ),
                )

            # 10. Read the generated code's result from result.json.
            try:
                final_result = self._read_final_answer(container)
            except (docker.errors.DockerException, FileNotFoundError,
                    KeyError, tarfile.TarError, OSError, ValueError) as exc:
                return ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    truncated=truncated,
                    error=f"Failed to read sandbox result.json: {exc}",
                )

            # 11. Apply the output byte limit to captured code output too.
            output_stdout = final_result.get("stdout", "")
            output_stderr = final_result.get("stderr", "")
            max_bytes = self.config.max_output_bytes
            stdout_bytes = output_stdout.encode("utf-8")
            stderr_bytes = output_stderr.encode("utf-8")
            if len(stdout_bytes) + len(stderr_bytes) > max_bytes:
                truncated = True
                stdout_bytes = stdout_bytes[:max_bytes // 2]
                stderr_bytes = stderr_bytes[:max_bytes - max_bytes // 2]
                output_stdout = stdout_bytes.decode("utf-8", errors="replace")
                output_stderr = stderr_bytes.decode("utf-8", errors="replace")

            return ExecutionResult(
                stdout=output_stdout,
                stderr=output_stderr,
                truncated=truncated,
                error=final_result.get("error"),
                is_final_answer=final_result.get("called", False),
                final_answer_value=final_result.get("value"),
            )

        except ImportError as exc:
            return ExecutionResult(
                error=str(exc)
            )

        except docker.errors.DockerException as exc:
            print("[DEBUG] Docker exception:", flush=True)
            traceback.print_exc()
            self._debug_container(container)
            return ExecutionResult(error=f"Docker error: {exc}")

        except Exception as exc:
            print("[DEBUG] Unexpected exception:", flush=True)
            traceback.print_exc()
            self._debug_container(container)
            return ExecutionResult(error=f"Sandbox error: {exc}")

        finally:
            # 12. Close Docker attachment
            if connection is not None:
                try:
                    self._close_attachment(connection)
                except Exception as exc:
                    print(f"[DEBUG] Attachment cleanup error: {exc}", flush=True)

            # 13. Remove container
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    pass

    def _cleanup_volumes(self) -> None:
        """Remove task volumes."""

        for volume in (self.testbed_volume, self.agent_volume):
            if volume is not None:
                try:
                    volume.remove()
                except docker.errors.DockerException:
                    pass

        self.testbed_volume = None
        self.agent_volume = None

    def close(self) -> None:
        """Close the Docker client."""
        self._cleanup_volumes()
        self.client.close()
