
import json
import os
from pathlib import Path
from typing import Optional

from schemas.sandbox import ExecutionResult


TESTBED_ROOT = "/testbed"
COMMAND_TIMEOUT = 30
MAX_OUTPUT_CHARS = 50_000

TEST_COMMAND = os.getenv(
    "SWEBENCH_TEST_COMMAND",
    "python -m pytest -q"
)

# Inject the DockerRunner instance during MCP server initialization.
_runner = None


def configure_runner(runner) -> None:
    """Configure the DockerRunner used by these tools."""
    global _runner
    _runner = runner


def _get_runner():
    if _runner is None:
        raise RuntimeError(
            "DockerRunner is not configured. "
            "Call configure_runner() first."
        )
    return _runner


def _execute_python(code: str) -> ExecutionResult:
    """Execute Python code through the Docker sandbox."""
    return _get_runner().run(code)


def _format_result(result: ExecutionResult) -> str:
    """Convert ExecutionResult into an agent-readable response."""

    output = []

    if result.stdout:
        output.append(f"STDOUT:\n{result.stdout}")

    if result.stderr:
        output.append(f"STDERR:\n{result.stderr}")

    if result.error:
        output.append(f"ERROR:\n{result.error}")

    if result.timed_out:
        output.append("Execution timed out.")

    if result.truncated:
        output.append("Output was truncated.")

    return "\n\n".join(output) if output else "Command produced no output."


# ---------------------------------------------------------
# 1. Run a shell command inside Docker
# ---------------------------------------------------------

def run_command(command: str, workdir: str) -> str:
    """
    Execute a shell command inside the Docker sandbox.

    Args:
        command: Shell command to execute.
        workdir: Working directory inside /testbed.

    Returns:
        Command output and exit status.
    """
    if not command or not command.strip():
        raise ValueError("command cannot be empty")

    # Generate Python code executed inside the sandbox.
    # repr() safely encodes user-provided strings as Python literals.
    code = f'''
import os
import json
from pathlib import Path

root = Path({TESTBED_ROOT!r}).resolve()
requested_dir = Path({workdir!r})

if not requested_dir.is_absolute():
    requested_dir = root / requested_dir

cwd = requested_dir.resolve()

try:
    cwd.relative_to(root)
except ValueError:
    raise PermissionError("Working directory is outside /testbed")

if not cwd.is_dir():
    raise NotADirectoryError(str(cwd))

os.chdir(cwd)

command = {command!r}

# Execute the command inside the sandbox.
# stderr is redirected to stdout to collect both streams.
pipe = os.popen(command + " 2>&1", "r")
output = pipe.read()
status = pipe.close()

if status is None:
    exit_code = 0
else:
    exit_code = os.waitstatus_to_exitcode(status)

print(json.dumps({{
    "output": output,
    "exit_code": exit_code
}}))
'''

    result = _execute_python(code)

    if result.timed_out:
        return _format_result(result)

    if result.error:
        return _format_result(result)

    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        return _format_result(result)

    output = data["output"]
    exit_code = data["exit_code"]

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n[Output truncated]"

    return (
        f"Exit code: {exit_code}\n"
        f"Timed out: False\n\n"
        f"{output}"
    )


# ---------------------------------------------------------
# 2. Run SWE-bench tests
# ---------------------------------------------------------

def run_tests() -> str:
    """
    Run the configured SWE-bench test command inside Docker.
    """
    return run_command(
        command=TEST_COMMAND,
        workdir=TESTBED_ROOT
    )


# ---------------------------------------------------------
# 3. Retrieve Git patch
# ---------------------------------------------------------

def get_patch() -> str:
    """
    Retrieve staged and unstaged changes compared with HEAD.
    """
    return run_command(
        command="git diff --no-ext-diff --no-color --unified=3 HEAD --",
        workdir=TESTBED_ROOT
    )
