import asyncio
import json
import posixpath
import select
import subprocess
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound

from sandbox.import_guard import ImportGuard
from schemas.sandbox import ExecutionResult, SandboxConfig


_SANDBOX_IMAGE = "agent-sandbox:latest"
_MCP_CALL_SAFETY_TIMEOUT_SECONDS = 600.0


def _extract_frames(buffer: bytearray) -> list[tuple[int, bytes]]:
    frames: list[tuple[int, bytes]] = []
    while len(buffer) >= 8:
        stream_id = buffer[0]
        length = int.from_bytes(buffer[4:8], "big")
        if len(buffer) < 8 + length:
            break
        payload = bytes(buffer[8 : 8 + length])
        del buffer[: 8 + length]
        frames.append((stream_id, payload))
    return frames


def _truncate_streams(
    stdout: str,
    stderr: str,
    max_bytes: int,
) -> tuple[str, str, bool]:
    stdout_bytes = stdout.encode("utf-8", errors="replace")
    stderr_bytes = stderr.encode("utf-8", errors="replace")
    if len(stdout_bytes) + len(stderr_bytes) <= max_bytes:
        return stdout, stderr, False

    stdout_limit = max_bytes // 2
    stderr_limit = max_bytes - stdout_limit
    return (
        stdout_bytes[:stdout_limit].decode("utf-8", errors="replace"),
        stderr_bytes[:stderr_limit].decode("utf-8", errors="replace"),
        True,
    )


class DockerRunner:
    """Manages a persistent, locked-down Docker container for sandboxed Python."""

    def __init__(
        self,
        config: SandboxConfig,
        mcp_manager: Any = None,
    ) -> None:
        self.config = config
        self.mcp_manager = mcp_manager
        self.client = docker.from_env()
        self.image = _SANDBOX_IMAGE
        self.import_guard = ImportGuard(config.authorized_imports)

        self._container = None
        self._connection = None
        self._frame_buffer = bytearray()
        self._stdout_buffer = bytearray()

        self._ensure_image()

    def _ensure_image(self) -> None:
        """Build the reusable lightweight sandbox image if missing."""
        try:
            self.client.images.get(self.image)
            return
        except ImageNotFound:
            pass

        context = Path(__file__).resolve().parent
        repository_root = context.parent
        dockerfile = repository_root / "Dockerfile"
        if not dockerfile.is_file():
            dockerfile = context / "Dockerfile"

        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "BASE_IMAGE=python:3.10-slim",
                "-t",
                self.image,
                "-f",
                str(dockerfile),
                str(repository_root),
            ],
            check=True,
        )

    def _build_tmpfs_mounts(self) -> dict[str, str]:
        """Mount writable tmpfs for each configured allowed_directory."""
        normalized: list[str] = []
        for raw_dir in self.config.allowed_directories:
            norm = posixpath.normpath(raw_dir)
            if not norm.startswith("/") or norm == "/":
                continue
            if norm not in normalized:
                normalized.append(norm)

        # Avoid overlapping nested tmpfs mounts (parent covers child).
        normalized.sort(key=len)
        roots: list[str] = []
        for path in normalized:
            if any(path.startswith(parent + "/") for parent in roots):
                continue
            roots.append(path)

        size_mb = max(16, int(self.config.max_disk_usage_mb))
        mount_opts = f"rw,noexec,nosuid,size={size_mb}m,mode=1777"
        return {path: mount_opts for path in roots}

    def _build_container_config(self) -> dict[str, Any]:
        mem_spec = f"{self.config.max_memory_mb}m"
        return {
            "image": self.image,
            "working_dir": "/testbed",
            "network_mode": "none",
            "stdin_open": True,
            "tty": False,
            "detach": True,
            "user": "1000:1000",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "read_only": True,
            "tmpfs": self._build_tmpfs_mounts(),
            "pids_limit": self.config.max_processes,
            "mem_limit": mem_spec,
            "memswap_limit": mem_spec,
        }

    def _close_attachment(self, connection: Any) -> None:
        if connection is None:
            return
        response = getattr(connection, "_response", None)
        try:
            if response is not None:
                response.close()
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass

    def _destroy_container(self) -> None:
        connection = self._connection
        container = self._container
        self._connection = None
        self._container = None
        self._frame_buffer.clear()
        self._stdout_buffer.clear()

        self._close_attachment(connection)
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass

    def _check_oom(self, container: Any) -> bool:
        try:
            container.reload()
            state = container.attrs.get("State") or {}
            return bool(state.get("OOMKilled")) or state.get("ExitCode") == 137
        except DockerException:
            return False

    def _send_json_line(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            raise RuntimeError("Sandbox IPC connection is closed")
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self._connection._sock.sendall(data)

    def _read_next_message_sync(
        self,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Read one JSON IPC message from container stdout; returns None on EOF."""
        if self._connection is None:
            return None
        sock = self._connection._sock
        deadline = time.monotonic() + timeout_seconds

        while True:
            if b"\n" in self._stdout_buffer:
                line, _, remaining = self._stdout_buffer.partition(b"\n")
                self._stdout_buffer = bytearray(remaining)
                if not line.strip():
                    continue
                return json.loads(line.decode("utf-8", errors="replace"))

            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise TimeoutError("Sandbox execution timed out")

            readable, _, _ = select.select(
                [sock], [], [], min(0.05, remaining_time)
            )
            if not readable:
                continue

            chunk = sock.recv(65536)
            if not chunk:
                return None

            self._frame_buffer.extend(chunk)
            for stream_id, payload in _extract_frames(self._frame_buffer):
                if stream_id == 1:
                    self._stdout_buffer.extend(payload)

    def _collect_container_diagnostics(self, container: Any) -> str:
        try:
            container.reload()
            state = container.attrs.get("State") or {}
            exit_code = state.get("ExitCode")
            state_error = state.get("Error") or ""
            logs = (
                container.logs(stdout=True, stderr=True)
                .decode("utf-8", errors="replace")
                .strip()
            )
            return (
                f"exit_code={exit_code}, state_error={state_error!r}, "
                f"logs={logs[-500:]!r}"
            )
        except Exception as exc:
            return f"(failed to read container logs: {exc})"

    def _ensure_container(self) -> None:
        if self._container is not None:
            try:
                self._container.reload()
                if self._container.attrs.get("State", {}).get("Running"):
                    return
            except DockerException:
                pass
            self._destroy_container()

        container = self.client.containers.create(**self._build_container_config())
        connection = container.attach_socket(
            params={"stdin": 1, "stdout": 1, "stream": 1}
        )
        container.start()

        self._container = container
        self._connection = connection
        self._frame_buffer.clear()
        self._stdout_buffer.clear()

        try:
            self._send_json_line({
                "type": "init",
                "authorized_imports": self.config.authorized_imports,
                "allowed_directories": self.config.allowed_directories,
            })
            ready = self._read_next_message_sync(timeout_seconds=15.0)
            if not ready or ready.get("type") != "ready":
                details = self._collect_container_diagnostics(container)
                raise RuntimeError(
                    f"Sandbox container failed to initialize ({details})"
                )
        except BaseException:
            self._destroy_container()
            raise

    async def _dispatch_mcp_request(
        self,
        request: dict[str, Any],
        allowed_tools: set[str],
    ) -> dict[str, Any]:
        req_id = request.get("id")
        req_type = request.get("type")

        try:
            if self.mcp_manager is None:
                raise RuntimeError("MCP manager not configured")

            if req_type == "tool_call":
                tool_name = request["name"]
                if tool_name not in allowed_tools:
                    raise RuntimeError(f"Unauthorized MCP tool: {tool_name}")

                result = await self.mcp_manager.call_tool(
                    tool_name,
                    request.get("arguments", {}),
                )
                texts = [
                    getattr(item, "text", str(item))
                    for item in result.content
                ]
                combined = "\n".join(texts)
                if result.isError:
                    raise RuntimeError(combined or "MCP tool reported an error")
                return {
                    "type": "tool_result",
                    "id": req_id,
                    "success": True,
                    "result": combined,
                }

            if req_type == "mcp_list_resources":
                return {
                    "type": "mcp_result",
                    "id": req_id,
                    "success": True,
                    "result": self.mcp_manager.list_resources(),
                }

            if req_type == "mcp_read_resource":
                res = await self.mcp_manager.read_resource(request["uri"])
                parts = []
                for content in res.contents:
                    if hasattr(content, "text") and content.text is not None:
                        parts.append(content.text)
                    elif hasattr(content, "blob") and content.blob is not None:
                        parts.append(str(content.blob))
                return {
                    "type": "mcp_result",
                    "id": req_id,
                    "success": True,
                    "result": "\n".join(parts),
                }

            if req_type == "mcp_list_prompts":
                return {
                    "type": "mcp_result",
                    "id": req_id,
                    "success": True,
                    "result": self.mcp_manager.list_prompts(),
                }

            if req_type == "mcp_get_prompt":
                res = await self.mcp_manager.get_prompt(
                    request["name"],
                    request.get("arguments") or {},
                )
                messages = [
                    {
                        "role": msg.role,
                        "content": getattr(msg.content, "text", str(msg.content)),
                    }
                    for msg in res.messages
                ]
                return {
                    "type": "mcp_result",
                    "id": req_id,
                    "success": True,
                    "result": messages,
                }

            raise RuntimeError(f"Unknown IPC request type: {req_type}")

        except Exception as exc:
            return {
                "type": "tool_result",
                "id": req_id,
                "success": False,
                "error": str(exc),
            }

    async def run(
        self,
        code: str,
        tools: list[Any] | None = None,
    ) -> ExecutionResult:
        """Execute Python code in the persistent sandbox container."""
        safe_tools = tools or []
        discovered_tool_names = {tool.name for tool in safe_tools}

        # 1. Static import and syntax validation before touching the container.
        try:
            self.import_guard.validate(code)
        except ImportError as exc:
            return ExecutionResult(error=f"ImportError: {exc}")
        except SyntaxError as exc:
            return ExecutionResult(
                error=f"SyntaxError: {exc.msg} (line {exc.lineno})"
            )

        partial_stdout: list[str] = []
        partial_stderr: list[str] = []

        try:
            await asyncio.to_thread(self._ensure_container)

            discovered_tools = [
                {
                    "name": tool.name,
                    "inputSchema": tool.inputSchema,
                }
                for tool in safe_tools
            ]

            await asyncio.to_thread(
                self._send_json_line,
                {"type": "exec", "code": code, "tools": discovered_tools},
            )

            # Budget applies ONLY to sandboxed Python code, NOT external MCP calls.
            remaining_budget = float(self.config.max_execution_time_seconds)

            while True:
                if remaining_budget <= 0:
                    raise TimeoutError("Sandbox execution timed out")

                wait_start = time.monotonic()
                msg = await asyncio.to_thread(
                    self._read_next_message_sync,
                    remaining_budget,
                )
                remaining_budget -= time.monotonic() - wait_start

                if msg is None:
                    # Container exited unexpectedly (likely OOM or crash).
                    container = self._container
                    oom = container is not None and await asyncio.to_thread(
                        self._check_oom, container
                    )
                    self._destroy_container()
                    stdout, stderr, truncated = _truncate_streams(
                        "".join(partial_stdout),
                        "".join(partial_stderr),
                        self.config.max_output_bytes,
                    )
                    if oom:
                        return ExecutionResult(
                            stdout=stdout,
                            stderr=stderr,
                            truncated=truncated,
                            error=(
                                f"Execution exceeded the memory limit "
                                f"({self.config.max_memory_mb} MB)."
                            ),
                            resource_limit_exceeded=True,
                        )
                    return ExecutionResult(
                        stdout=stdout,
                        stderr=stderr,
                        truncated=truncated,
                        error="Sandbox container exited unexpectedly.",
                    )

                msg_type = msg.get("type")

                if msg_type == "stream":
                    stream = msg.get("stream")
                    data = msg.get("data", "")
                    if stream == "stdout":
                        partial_stdout.append(data)
                    elif stream == "stderr":
                        partial_stderr.append(data)
                    continue

                if msg_type in (
                    "tool_call",
                    "mcp_list_resources",
                    "mcp_read_resource",
                    "mcp_list_prompts",
                    "mcp_get_prompt",
                ):
                    # Sandbox execution timer is paused during external MCP call.
                    response = await asyncio.wait_for(
                        self._dispatch_mcp_request(msg, discovered_tool_names),
                        timeout=_MCP_CALL_SAFETY_TIMEOUT_SECONDS,
                    )
                    await asyncio.to_thread(self._send_json_line, response)
                    continue

                if msg_type == "exec_result":
                    control_exc = msg.get("control_exception")
                    if control_exc == "KeyboardInterrupt":
                        self._destroy_container()
                        raise KeyboardInterrupt(msg.get("error", ""))
                    if control_exc == "SystemExit":
                        self._destroy_container()
                        raise SystemExit(msg.get("error", ""))

                    stdout, stderr, truncated = _truncate_streams(
                        msg.get("stdout", ""),
                        msg.get("stderr", ""),
                        self.config.max_output_bytes,
                    )
                    return ExecutionResult(
                        stdout=stdout,
                        stderr=stderr,
                        error=msg.get("error"),
                        truncated=truncated,
                        is_final_answer=bool(msg.get("called", False)),
                        final_answer_value=msg.get("value"),
                        resource_limit_exceeded=bool(
                            msg.get("resource_limit_exceeded", False)
                        ),
                    )

        except TimeoutError:
            self._destroy_container()
            stdout, stderr, truncated = _truncate_streams(
                "".join(partial_stdout),
                "".join(partial_stderr),
                self.config.max_output_bytes,
            )
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                truncated=truncated,
                error=(
                    f"Execution timed out after "
                    f"{self.config.max_execution_time_seconds} seconds."
                ),
                timed_out=True,
            )

        except (KeyboardInterrupt, SystemExit):
            self._destroy_container()
            raise

        except DockerException as exc:
            self._destroy_container()
            return ExecutionResult(error=f"Docker error: {exc}")

        except Exception as exc:
            self._destroy_container()
            return ExecutionResult(error=f"Sandbox error: {exc}")

    def close(self) -> None:
        """Shut down the sandbox container and close the Docker client."""
        try:
            if self._connection is not None:
                self._send_json_line({"type": "shutdown"})
        except Exception:
            pass
        self._destroy_container()
        try:
            self.client.close()
        except Exception:
            pass
