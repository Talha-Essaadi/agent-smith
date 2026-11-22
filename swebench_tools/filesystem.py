import ast
import fnmatch
from pathlib import Path

from swebench_tools.backend import (
    docker_exec_python,
    is_docker_mode,
    resolve_container_path,
    resolve_local_path,
    get_testbed_root,
    truncate_output,
)

from .container_scripts import (
    _CONTAINER_READ_SCRIPT,
    _CONTAINER_EDIT_SCRIPT,
    _CONTAINER_LIST_SCRIPT
)


def read_file(
    filepath: str,
    start_line: int,
    end_line: int
) -> str:
    """Read lines from a file with 1-based line numbers
     (`<line_number>: <line_content>`)."""
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line is not None and end_line < start_line:
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





