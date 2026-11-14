
import docker
import requests
import io
import json
import tarfile
from docker.errors import ImageNotFound
from schemas.sandbox import SandboxConfig, ExecutionResult
from typing import Optional
from .import_guard import ImportGuard
from pathlib import Path
import subprocess
import traceback
import logging

class DockerRunner:
    def __init__(self, config: SandboxConfig) -> None:
        """Store configuration and initialize the Docker client."""
        self.config = config
        self.client = docker.from_env()
        self.image = "python:3.10-slim"  # DEBUG: verify /testbed/main.py exists in mounted volume
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

    def _ensure_image(self) -> None:
        """Build the Docker image from the local Dockerfile if missing."""

        try:
            self.client.images.get(self.image)
            print(f"Image {self.image} already exists.")
            return

        except ImageNotFound:
            print("Building sandbox image...")

            context = Path(__file__).resolve().parent

            subprocess.run(
                [
                    "docker", "build",
                    "-t", self.image,
                    "-f", str(context / "Dockerfile"),
                    str(context),
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

    def _handle_execution_timeout(
        self,
        container,
        exc: Exception,
    ) -> ExecutionResult:
        """Handle execution timeout or Docker communication failure."""
        print("[DEBUG] Docker wait failed:", repr(exc), flush=True)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        self._debug_container(container)
        try:
            container.kill()
        except docker.errors.DockerException as kill_exc:
            print("[DEBUG] Kill failed:", repr(kill_exc), flush=True)

        return ExecutionResult(
            error=f"Execution timed out or Docker communication failed: {exc}",
            timed_out=True,
        )

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
        """Best-effort diagnostics; never hide the original exception."""
        if container is None:
            return
        print(f"[DEBUG] Container ID: {container.id}", flush=True)
        try:
            container.reload()
            print("[DEBUG] State:", container.attrs.get("State"), flush=True)
            print("[DEBUG] Image:", container.attrs.get("Config", {}).get("Image"), flush=True)
            print("[DEBUG] Command:", container.attrs.get("Config", {}).get("Cmd"), flush=True)
        except Exception as exc:
            print("[DEBUG] Inspect failed:", repr(exc), flush=True)
        try:
            out, err = container.logs(stdout=True, stderr=True, demux=True)
            print("[DEBUG] STDOUT:", (out or b"").decode(errors="replace")[-4000:], flush=True)
            print("[DEBUG] STDERR:", (err or b"").decode(errors="replace")[-4000:], flush=True)
        except Exception as exc:
            print("[DEBUG] Logs failed:", repr(exc), flush=True)

    def run(self, code: str) -> ExecutionResult:
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
                    "stream": 1,
                }
            )

            # 4. Start container
            container.start()
            print("[DEBUG] Container started", flush=True)

            # 5. Send code as one JSON line
            message = json.dumps({"code": code}) + "\n"

            connection._sock.sendall(
                message.encode("utf-8")
            )

            print("[DEBUG] Sent JSON line:", len(message), "characters", flush=True)

            # No shutdown(1) needed.
            # The container reads until newline.

            # 6. Wait for execution
            try:
                print("[DEBUG] Waiting for container to exit...", flush=True)
                result = container.wait(
                    timeout=self.config.max_execution_time_seconds
                )
                print("[DEBUG] Exit status:", result, flush=True)

            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                return self._handle_execution_timeout(
                    container, exc
                )

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

            # 10. Read final_answer() result
            try:
                final_result = self._read_final_answer(container)
            except (docker.errors.NotFound, FileNotFoundError, KeyError, tarfile.TarError) as exc:
                print("[DEBUG] Final-answer metadata unavailable:", repr(exc), flush=True)
                final_result = {"called": False, "value": None}

            # 11. Return execution result
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                truncated=truncated,
                error=None,
                is_final_answer=final_result["called"],
                final_answer_value=final_result["value"],
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
