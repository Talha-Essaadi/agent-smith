import shutil
import subprocess
import tempfile
from typing import Tuple, Optional
from pathlib import Path

import docker
from docker.errors import ImageNotFound, DockerException


class SWEBenchDockerManager:
    def __init__(self, docker_image: str) -> None:
        self.docker_image = docker_image
        self.client = docker.from_env()
        self.container = None
        self._testbed_dir: Optional[Path] = None
        self._temp_root: Optional[Path] = None

    def _ensure_image(self) -> None:
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            self.client.images.pull(self.docker_image)

    def _extract_testbed(self) -> Path:
        target = self._temp_root / "testbed"
        tmp_container = self.client.containers.create(
            self.docker_image, command="true")
        try:
            subprocess.run(
                ["docker", "cp",
                f"{tmp_container.id}:/testbed",
                str(target)], check=True)
        finally:
            tmp_container.remove(force=True)
        return target

    def _launch_container(self) -> "docker.models.containers.Container":
        return self.client.containers.run(
            self.docker_image,
            command=["sleep", "infinity"],
            detach=True,
            working_dir="/testbed",
            network_mode="none",
            volumes={
                str(self._testbed_dir): {"bind": "/testbed", "mode": "rw"}
            })


    def start(self) -> Tuple[str, Path]:
        if self.container is not None:
            raise RuntimeError(
                "Container already started; call close() first.")
        try:
            self._ensure_image()
            self._temp_root = Path(tempfile.mkdtemp(prefix="swebench_"))
            self._testbed_dir = self._extract_testbed()
            self.container = self._launch_container()
        except BaseException:
            self.close()
            raise
        return self.container.id, self._testbed_dir

    def close(self) -> None:
        if self.container is not None:
            try:
                self.container.remove(force=True)
            except DockerException:
                pass
            self.container = None
        if self._temp_root is not None:
            shutil.rmtree(self._temp_root, ignore_errors=True)
            self._temp_root = None
            self._testbed_dir = None

        try:
            self.client.close()
        except Exception:
            pass

    @property
    def container_id(self) -> str:
        if self.container is None:
            raise RuntimeError("SWE-bench container has not been started.")
        return self.container.id

    @property
    def testbed_dir(self) -> Path:
        if self._testbed_dir is None:
            raise RuntimeError(
                "testbed directory not initialized. Call start() first.")
        return self._testbed_dir
