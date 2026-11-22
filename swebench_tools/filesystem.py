import ast
import fnmatch
from pathlib import Path

from .backend import (
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
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """Read lines from a file with 1-based line numbers (`<line_number>: <line_content>`)."""
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    if is_docker_mode():
        target = resolve_container_path(filepath)
        output = docker_exec_python(
            _CONTAINER_READ_SCRIPT,
            {"filepath": target, "start_line": start_line, "end_line": end_line},
        )
        return truncate_output(output)

    path = resolve_local_path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if start_line > len(lines):
        return f"File contains only {len(lines)} lines."

    actual_end = len(lines) if end_line is None else min(end_line, len(lines))
    formatted = [f"{ln}: {lines[ln - 1]}" for ln in range(start_line, actual_end + 1)]
    return truncate_output("\n".join(formatted))


def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace an exact unique string in a file with a new string."""
    if not old_str:
        raise ValueError("old_str cannot be empty")

    if is_docker_mode():
        target = resolve_container_path(filepath)
        return docker_exec_python(
            _CONTAINER_EDIT_SCRIPT,
            {
                "filepath": target,
                "display_path": filepath,
                "old_str": old_str,
                "new_str": new_str,
            },
        )

    path = resolve_local_path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8")
    occurrences = content.count(old_str)
    if occurrences == 0:
        raise ValueError("old_str was not found in the file")
    if occurrences > 1:
        raise ValueError(
            f"old_str appears {occurrences} times. Provide a more specific string."
        )

    updated = content.replace(old_str, new_str, 1)
    path.write_text(updated, encoding="utf-8")

    msg = f"Successfully edited {filepath}"
    if path.suffix == ".py":
        try:
            ast.parse(updated, filename=str(path))
        except SyntaxError as exc:
            msg += f"\n[WARNING: SyntaxError introduced at line {exc.lineno}: {exc.msg}]"
    return msg


def list_files(directory: str = ".", pattern: str = "*") -> str:
    """List files inside a directory matching a glob pattern."""
    if is_docker_mode():
        target = resolve_container_path(directory)
        output = docker_exec_python(
            _CONTAINER_LIST_SCRIPT,
            {"directory": target, "display_dir": directory, "pattern": pattern or "*"},
        )
        return truncate_output(output)

    root = get_testbed_root()
    base = resolve_local_path(directory)
    if not base.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    glob_pat = pattern or "*"
    results: list[str] = []

    for item in base.rglob("*"):
        if ".git" in item.parts:
            continue
        try:
            if not item.is_file():
                continue
            item.resolve().relative_to(root)
        except (ValueError, OSError, RuntimeError):
            continue

        rel_dir = item.relative_to(base).as_posix()
        if fnmatch.fnmatch(item.name, glob_pat) or fnmatch.fnmatch(rel_dir, glob_pat):
            results.append(item.relative_to(root).as_posix())

    if not results:
        return f"No files matching '{glob_pat}' found in '{directory}'."

    return truncate_output("\n".join(sorted(results)))
