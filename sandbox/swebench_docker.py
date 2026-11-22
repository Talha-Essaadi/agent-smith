
import shutil
import subprocess

import docker
from docker.errors import ImageNotFound

from config.paths import TESTBED_PATH


class SWEBenchDockerManager:
    def __init__(self, docker_image: str) -> None:
        self.docker_image = docker_image
        self.client = docker.from_env()

    def _ensure_image(self) -> None:
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            self.client.images.pull(self.docker_image)

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
