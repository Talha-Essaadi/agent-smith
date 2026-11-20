from pathlib import Path
import fnmatch
import os
# from sandbox.docker_backend import run_in_container

# Abdo Debug # This hardcoded root ignores TESTBED_PATH set by the moulinette's isolated tests.
TESTBED_ROOT = (
    Path.home() / "agent-workspaces" / "testbed"
).resolve()

def pwd() -> str:
    """Return the working directory inside the SWE-bench container."""
    # return run_in_container(["pwd"])
    return os.getcwd()




# def _resolve_path(path: str) -> Path:
#     """
#     Resolve a path and ensure it stays inside /testbed.
#     Accepts both relative and absolute paths.
#     """
#     candidate = Path(path)

#     if not candidate.is_absolute():
#         candidate = TESTBED_ROOT / candidate

#     resolved = candidate.resolve()

#     try:
#         resolved.relative_to(TESTBED_ROOT)
#     except ValueError:
#         raise PermissionError(
#             f"Access denied: '{path}' is outside {TESTBED_ROOT}"
#         )

#     return resolved


def _resolve_path(directory: str) -> Path:
    """Resolve a directory inside the shared workspace."""

    requested = Path(directory)

    # Support Docker-style paths such as /testbed/src
    # Abdo Debug # Search uses /testbed directly, but read_file maps it to a different local root.
    # Abdo Debug # Absolute paths under a custom TESTBED_PATH are rejected here.
    if requested.is_absolute():
        try:
            requested = requested.relative_to("/testbed")
        except ValueError:
            raise ValueError(
                "Absolute paths must be inside /testbed"
            ) from None

    path = (TESTBED_ROOT / requested).resolve()

    # Prevent access outside the shared workspace
    if not path.is_relative_to(TESTBED_ROOT):
        raise ValueError(
            f"Access outside shared workspace is forbidden: {directory}"
        )

    return path



def read_file(filepath: str, start_line: int, end_line: int) -> str:
    """
    Read a specific range of lines from a file.

    Line numbers are 1-based and inclusive.
    Output includes line numbers, similar to `cat -n`.
    """
    # Abdo Debug # This debug print writes to stdout and can corrupt MCP stdio JSON-RPC messages.
    print(f"*********************{pwd()}")
    if start_line < 1:
        raise ValueError("start_line must be >= 1")

    if end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    path = _resolve_path(filepath)

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    lines = path.read_text(encoding="utf-8").splitlines()

    if start_line > len(lines):
        return f"File contains only {len(lines)} lines."

    end_line = min(end_line, len(lines))

    result = []
    for line_number in range(start_line, end_line + 1):
        content = lines[line_number - 1]
        result.append(f"{line_number:6}\t{content}")
    return "\n".join(result)


def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """
    Replace an exact string in a file.

    Requires exactly one occurrence of old_str to avoid
    accidentally modifying multiple locations.
    """
    if not old_str:
        raise ValueError("old_str cannot be empty")

    path = _resolve_path(filepath)

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8")

    occurrences = content.count(old_str)

    if occurrences == 0:
        raise ValueError("old_str was not found in the file")

    if occurrences > 1:
        raise ValueError(
            f"old_str appears {occurrences} times. "
            "Provide a more specific string."
        )

    updated_content = content.replace(old_str, new_str, 1)

    # Abdo Debug # Edited Python is saved without syntax validation, so invalid code is reported as success.
    path.write_text(updated_content, encoding="utf-8")

    return f"Successfully edited {filepath}"



def list_files(directory: str = ".", pattern: str = "*") -> str:
    """
    List files in the shared Docker workspace.

    Examples:
        list_files(".", "*.py")
        list_files("src", "*.c")
        list_files("agent", "**/*.py")
        list_files("/testbed", "*.py")
    """

    path = _resolve_path(directory)

    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    pattern = pattern or "*"
    results = []

    for item in path.rglob("*"):
        try:
            if not item.is_file():
                continue

            # Skip symbolic links pointing outside the workspace
            item.resolve().relative_to(TESTBED_ROOT)

        except (ValueError, OSError, RuntimeError):
            continue

        relative_path = item.relative_to(path).as_posix()

        if fnmatch.fnmatch(relative_path, pattern):
            results.append(
                item.relative_to(TESTBED_ROOT).as_posix()
            )

    if not results:
        return (
            f"No files matching '{pattern}' "
            f"found in '{directory}'."
        )

    return "\n".join(sorted(results))





