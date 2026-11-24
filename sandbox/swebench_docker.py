import docker
from docker.errors import DockerException, ImageNotFound


class SWEBenchDockerManager:
    """Manages one persistent Docker container for a SWE-bench task."""

    def __init__(self, docker_image: str) -> None:
        if not docker_image or not docker_image.strip():
            raise ValueError("SWE-bench requires a valid docker_image")

        self.docker_image = docker_image.strip()
        self.client = docker.from_env()
        self.container = None

    def _ensure_image(self) -> None:
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            self.client.images.pull(self.docker_image)

    def start(self) -> str:
        """Pull image if needed, start persistent task container,
         return container ID."""
        if self.container is not None:
            raise RuntimeError("SWE-bench container is already started.")

        try:
            self._ensure_image()
            self.container = self.client.containers.run(
                self.docker_image,
                command=["tail", "-f", "/dev/null"],
                working_dir="/testbed",
                network_mode="none",
                detach=True,
                tty=False,
            )
            return self.container.id
        except BaseException:
            self.close()
            raise

    @property
    def container_id(self) -> str:
        if self.container is None:
            raise RuntimeError("SWE-bench container has not been started.")
        return self.container.id

    def close(self) -> None:
        """Force-remove the task container and close the Docker client."""
        container = self.container
        self.container = None
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass
        try:
            self.client.close()
        except Exception:
            pass
