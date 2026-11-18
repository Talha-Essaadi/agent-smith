import os
import docker

docker_client = docker.from_env()



def run_in_container(
    command: list[str],
    workdir: str = "/testbed",
) -> str:
    CONTAINER_ID = os.environ["SWEBENCH_CONTAINER_ID"]
    container = docker_client.containers.get(CONTAINER_ID)

    result = container.exec_run(
        cmd=command,
        workdir=workdir,
        demux=True,
    )

    stdout, stderr = result.output

    stdout = (stdout or b"").decode("utf-8", errors="replace")
    stderr = (stderr or b"").decode("utf-8", errors="replace")

    if result.exit_code != 0:
        raise RuntimeError(
            f"Command failed (exit {result.exit_code}): {stderr}"
        )

    return stdout