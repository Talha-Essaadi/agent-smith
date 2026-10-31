
import docker
import requests

from docker.errors import ImageNotFound
from schemas.sandbox import SandboxConfig, ExecutionResult


class DockerRunner:
    def __init__(self, config: SandboxConfig) -> None:
        """Store configuration and initialize the Docker client."""
        self.config = config
        self.client = docker.from_env()
        self.image = "python:3.10-slim"
        self.testbed_volume = self.client.volumes.create(
            name=f"agent-testbed-{task_id}"
        )
        self.agent_volume = self.client.volumes.create(
            name=f"agent-tmp-{task_id}" # task_id ??
        )

        self.import_guard = ImportGuard(
            config.authorized_imports
        )
        self._initialize_volumes()
        self._ensure_image()

    def _ensure_image(self) -> None:
        """Pull the Docker image if it is missing locally."""
        try:
            self.client.images.get(self.image)
        except ImageNotFound:
            print(f"Image not found. Pulling {self.image}...")
            self.client.images.pull(self.image)
            print("Image pulled successfully.")

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

    def _build_container_config(self, code: str) -> dict:
        """Build Docker container settings."""

        
        return {
            "image": self.image,
            "command": ["python", "-c", code],
            "working_dir": "/testbed",
            "network_mode": "none",
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

    def run(self, code: str) -> ExecutionResult:
        """Execute code in an isolated container and return the result."""
        container = None

        try:
            self.import_guard.validate(code)
            container = self.client.containers.create(
                **self._build_container_config(code)
            )
            container.start()

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
            stdout, stderr, truncated = self._collect_output(container)
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                truncated=truncated,
            )

            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                error=(
                    f"Container exited with code {result['StatusCode']}"
                    if result["StatusCode"] != 0
                    else None
                ),
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

    def close(self) -> None:
        """Close the Docker client."""
        self.client.close()
