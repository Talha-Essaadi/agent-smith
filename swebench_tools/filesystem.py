
from pathlib import Path
import fnmatch


# All filesystem operations are restricted to the SWE-bench repository.
TESTBED_ROOT = Path("/testbed").resolve()


def _resolve_path(path: str) -> Path:
    """
    Resolve a path and ensure it stays inside /testbed.
    Accepts both relative and absolute paths.
    """
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = TESTBED_ROOT / candidate

    resolved = candidate.resolve()

    try:
        resolved.relative_to(TESTBED_ROOT)
    except ValueError:
        raise PermissionError(
            f"Access denied: '{path}' is outside {TESTBED_ROOT}"
        )

    return resolved


def read_file(filepath: str, start_line: int, end_line: int) -> str:
    """
    Read a specific range of lines from a file.

    Line numbers are 1-based and inclusive.
    Output includes line numbers, similar to `cat -n`.
    """
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

    path.write_text(updated_content, encoding="utf-8")

    return f"Successfully edited {filepath}"


def list_files(directory: str, pattern: str = "*") -> str:
    """
    List files matching a glob-style pattern in a directory.

    Examples:
        list_files(".", "*.py")
        list_files("src", "*.c")
        list_files("agent", "**/*.py")
    """
    path = _resolve_path(directory)

    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    if not pattern:
        pattern = "*"

    results = []

    for item in path.rglob("*"):
        # Do not follow symlinks outside the repository.
        try:
            resolved = item.resolve()
            resolved.relative_to(TESTBED_ROOT)
        except (ValueError, OSError):
            continue

        if item.is_file() and fnmatch.fnmatch(item.relative_to(path).as_posix(), pattern):
            results.append(str(item.relative_to(TESTBED_ROOT)))

    if not results:
        return f"No files matching '{pattern}' found in '{directory}'."

    return "\n".join(sorted(results))
