
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

        self._ensure_image()

    def _ensure_image(self) -> None:
        """Pull the Docker image if it is missing locally."""
        try:
            self.client.images.get(self.image)
        except ImageNotFound:
            print(f"Image not found. Pulling {self.image}...")
            self.client.images.pull(self.image)
            print("Image pulled successfully.")

    def _build_container_config(self, code: str) -> dict:
        """Build Docker container settings."""
        return {
            "image": self.image,
            "command": ["python", "-c", code],
            "mem_limit": f"{self.config.max_memory_mb}m",
            "network_mode": "none",
            "detach": True,
        }

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

    def run(self, code: str) -> ExecutionResult:
        """Execute code in an isolated container and return the result."""
        container = None

        try:
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
