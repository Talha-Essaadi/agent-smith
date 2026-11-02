
import docker
import requests
import io
import json
import tarfile
from docker.errors import ImageNotFound
from schemas.sandbox import SandboxConfig, ExecutionResult


class DockerRunner:
    def __init__(self, config: SandboxConfig) -> None:
        """Store configuration and initialize the Docker client."""
        self.config = config
        self.client = docker.from_env()
        self.image = "python:3.10-slim"
        self.testbed_volume = self.client.volumes.create(
            name=f"agent-testbed"
        )
        self.agent_volume = self.client.volumes.create(
            name=f"agent-tmp"
        )

        self.import_guard = ImportGuard(
            config.authorized_imports
        )
        self._initialize_volumes()
        self._ensure_image()

    def _ensure_image(self) -> None:
        """Build the Docker image from the local Dockerfile if missing."""
        try:
            self.client.images.get(self.image)
            print(f"Image {self.image} already exists.")

        except ImageNotFound:
            print(f"Image {self.image} not found. Building from Dockerfile...")

            self.client.images.build(
                path=".",                  # Build context
                dockerfile="sandbox/Dockerfile",   # Dockerfile path
                tag=self.image,
                rm=True,
            )

            print("Image built successfully.")

    def _initialize_volumes(self) -> None:
        """Set volume ownership to the non-root sandbox user."""
        init = self.client.containers.create(
            image=self.config.image,
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
        try:
            container.kill()
        except docker.errors.DockerException:
            pass

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
            raise SandboxExecutionError(
                f"Failed to inspect container state: {exc}"
            ) from exc

        return None

    def _collect_output(
        self,
        container,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> tuple[str, str, bool]:
        """Collect container output with a maximum byte limit."""

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
            "nano_cpus": int(self.config.max_cpu_cores * 1_000_000_000),
            "pids_limit": self.config.max_processes,
            "mem_limit": f"{self.config.max_memory_mb}m",
            "storage_opt": {
                "size": f"{self.config.max_disk_usage_mb}m"
            },

        }

    def _read_final_answer(self, container) -> dict:
        """Read the final answer result from the Docker container."""

        archive, _ = container.get_archive("/tmp/agent/result.json")

        with tarfile.open(fileobj=io.BytesIO(b"".join(archive)), mode="r:*") as tar:
            file = tar.extractfile("result.json")

            if file is None:
                raise FileNotFoundError("result.json not found in Docker archive")

            return json.load(file)


    def run(self, code: str) -> ExecutionResult:
        """Execute code in an isolated container and return the result."""
        container = None

        try:
            self.import_guard.validate(code)
            container = self.client.containers.create(
                **self._build_container_config()
            )
            container.start()

            socket = container.attach_socket(
                params={"stdin": 1, "stream": 1}
            )
            try:
                socket._sock.sendall(code.encode())
                socket._sock.shutdown(1)
            finally:
                socket.close()

            try:
                result = container.wait(
                    timeout=self.config.max_execution_time_seconds
                )
            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as exc:
            # 1 Handle time out restriction
                return self._handle_execution_timeout(container, exc)

            # 2 Handle memory limit restriction
            memory_error = self._handle_memory_limit(container)
            if memory_error:
                return memory_error

            # handle non-zero exit code
            if result["StatusCode"] != 0:
                return ExecutionResult(
                    error=f"Container exited with code {result['StatusCode']}."
                )

            # 3 handle truncated output restriction
            final_result = self._read_final_answer(container)
            stdout, stderr, truncated = self._collect_output(container)

            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                truncated=truncated,
                error=(
                    f"Container exited with code {result['StatusCode']}"
                    if result["StatusCode"] != 0
                    else None
                ),
                is_final_answer=final_result["called"],
                final_answer_value=final_result["value"]
            )
        # 4 Handle unauthorized imports
        except ImportError as e:
            return ExecutionResult(
                error=str(e)
            )

        except docker.errors.DockerException as exc:
            return ExecutionResult(
                error=f"Docker error: {exc}",
            )

        finally:
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
