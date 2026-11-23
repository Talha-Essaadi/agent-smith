import os
import sys

from .backend import is_docker_mode, run_shell, truncate_output


_COMMAND_TIMEOUT_SECONDS = 120
_TESTS_TIMEOUT_SECONDS = 300


def _format_command_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    timed_out: bool,
) -> str:
    parts = [f"Exit code: {exit_code}"]
    if timed_out:
        parts.append(
            "[WARNING: Command timed out; output below may be partial.]"
        )
    if stdout:
        parts.append(f"STDOUT:\n{stdout.rstrip()}")
    if stderr:
        parts.append(f"STDERR:\n{stderr.rstrip()}")
    if not stdout and not stderr and not timed_out:
        parts.append("(no output)")
    return truncate_output("\n\n".join(parts))


def run_command(command: str, workdir: str = "/testbed") -> str:
    """Execute a shell command in the specified working directory.

    Returns stdout, stderr, and exit code.
    """
    if not command or not command.strip():
        raise ValueError("command cannot be empty")

    stdout, stderr, exit_code, timed_out = run_shell(
        command=command,
        workdir=workdir,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    return _format_command_output(stdout, stderr, exit_code, timed_out)


def run_tests() -> str:
    """Execute the SWE-bench evaluation script
     (or fallback pytest in isolated mode)."""
    eval_script = os.environ.get("SWE_EVAL_SCRIPT", "").strip()
    if eval_script:
        stdout, stderr, exit_code, timed_out = run_shell(
            command="",
            workdir="/testbed",
            timeout=_TESTS_TIMEOUT_SECONDS,
            script_stdin=eval_script,
        )
        return _format_command_output(
            stdout, stderr, exit_code, timed_out
        )

    default_cmd = (
        "pytest -q"
        if is_docker_mode()
        else f'"{sys.executable}" -m pytest -q'
    )
    test_cmd = os.environ.get("SWEBENCH_TEST_COMMAND", default_cmd)
    stdout, stderr, exit_code, timed_out = run_shell(
        command=test_cmd,
        workdir="/testbed",
        timeout=_TESTS_TIMEOUT_SECONDS,
    )
    return _format_command_output(stdout, stderr, exit_code, timed_out)


def get_patch() -> str:
    """Retrieve the unified git diff of all changes made to the repository."""
    stdout, stderr, exit_code, timed_out = run_shell(
        command="git -c core.fileMode=false diff",
        workdir="/testbed",
        timeout=30,
    )
    if timed_out:
        raise RuntimeError("git diff timed out")
    if exit_code != 0:
        raise RuntimeError(
            f"git diff failed (exit {exit_code}): {stderr.strip()}"
        )
    return stdout
