<<<<<<< HEAD

import shutil
import subprocess

=======
>>>>>>> fix/neon
import docker
from docker.errors import ImageNotFound

from config.paths import TESTBED_PATH


class SWEBenchDockerManager:
    """Manages one persistent Docker container for a SWE-bench task."""

    def __init__(self, docker_image: str) -> None:
        if not docker_image or not docker_image.strip():
            raise ValueError("SWE-bench requires a valid docker_image")

        self.docker_image = docker_image.strip()
        self.client = docker.from_env()
<<<<<<< HEAD
=======
        self.container = None
>>>>>>> fix/neon

    def _ensure_image(self) -> None:
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            self.client.images.pull(self.docker_image)

<<<<<<< HEAD
    def _copy_testbed(self) -> None:
        tmp_container = self.client.containers.create(
            image=self.docker_image,
            command="true",
        )

        try:
            subprocess.run(
                [
                    "docker",
                    "cp",
                    f"{tmp_container.id}:/testbed/.",
                    str(TESTBED_PATH),
                ],
                check=True,
            )
        finally:
            tmp_container.remove(force=True)

    def prepare_testbed(self) -> None:
        self._ensure_image()

        # Remove files from a previous task
        if TESTBED_PATH.exists():
            shutil.rmtree(TESTBED_PATH)

        TESTBED_PATH.mkdir(parents=True, exist_ok=True)

        self._copy_testbed()

    def close(self) -> None:
        self.client.close()
=======
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
>>>>>>> fix/neon
