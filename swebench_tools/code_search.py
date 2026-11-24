import ast
import fnmatch
import os
import re
from pathlib import Path

from .backend import (
    docker_exec_python,
    get_testbed_root,
    is_docker_mode,
    resolve_container_path,
    resolve_local_path,
    truncate_output,
)

from .container_scripts import (
    _CONTAINER_SEARCH_CODE_SCRIPT,
    _CONTAINER_SEARCH_DEF_SCRIPT,
    _CONTAINER_FIND_REFS_SCRIPT
)


_MAX_MATCHES = 200


def _iter_repo_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fname in sorted(filenames):
            filepath = Path(dirpath) / fname
            try:
                filepath.resolve().relative_to(root)
            except (ValueError, OSError):
                continue
            if filepath.is_file():
                yield filepath


def search_code(pattern: str, file_pattern: str = "*") -> str:
    """Perform a grep-like search in
     the codebase (`/abs/path:<line> <content>`)."""
    if not pattern:
        raise ValueError("pattern cannot be empty")

    if is_docker_mode():
        output = docker_exec_python(
            _CONTAINER_SEARCH_CODE_SCRIPT,
            {
                "pattern": pattern,
                "file_pattern": file_pattern or "*",
                "max_matches": _MAX_MATCHES,
            },
        )
        return truncate_output(output)

    root = get_testbed_root()
    glob_pat = file_pattern or "*"
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = None

    results: list[str] = []
    truncated = False

    for filepath in _iter_repo_files(root):
        rel = filepath.relative_to(root).as_posix()
        if (not fnmatch.fnmatch(filepath.name, glob_pat)
                and not fnmatch.fnmatch(rel, glob_pat)):
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            matched = (
                bool(regex.search(line))
                if regex is not None
                else (pattern in line)
            )
            if matched:
                results.append(f"{filepath}:{lineno} {line}")
                if len(results) >= _MAX_MATCHES:
                    truncated = True
                    break
        if truncated:
            break

    if not results:
        return f"No matches found for '{pattern}'."

    output = "\n".join(results)
    if truncated:
        output += (
            f"\n[Output truncated at {_MAX_MATCHES} matches."
            " Narrow your pattern or file_pattern.]"
        )
    return truncate_output(output)


def search_function_or_class_definition_in_code(name: str) -> str:
    """Find function or class definitions by name using AST parsing."""
    if not name:
        raise ValueError("name cannot be empty")

    if is_docker_mode():
        output = docker_exec_python(
            _CONTAINER_SEARCH_DEF_SCRIPT,
            {"name": name}
        )
        return truncate_output(output)

    root = get_testbed_root()
    results: list[str] = []

    for filepath in _iter_repo_files(root):
        if filepath.suffix != ".py":
            continue
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        lines = source.splitlines()
        for node in ast.walk(tree):
            if (
                isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == name
            ):
                line_text = (
                    lines[node.lineno - 1].strip()
                    if node.lineno <= len(lines)
                    else name
                )
                results.append(f"{filepath}:{node.lineno} {line_text}")

    if not results:
        return f"No definition found for '{name}'."
    return truncate_output("\n".join(results))


def find_references(name: str, filepath: str = "", line: int = 0) -> str:
    """Find all usages of a Python symbol across the repository."""
    if not name or not name.isidentifier():
        raise ValueError("name must be a valid Python identifier")
    if filepath and line < 1:
        raise ValueError("line must be >= 1 when filepath is provided")

    if is_docker_mode():
        target = resolve_container_path(filepath) if filepath else ""
        output = docker_exec_python(
            _CONTAINER_FIND_REFS_SCRIPT,
            {
                "name": name,
                "filepath": target,
                "line": line,
                "max_matches": _MAX_MATCHES,
            },
        )
        return truncate_output(output)

    root = get_testbed_root()
    definition_path: Path | None = None
    if filepath:
        definition_path = resolve_local_path(filepath)
        if not definition_path.is_file():
            raise FileNotFoundError(f"File not found: {filepath}")

    results: list[str] = []
    seen: set[str] = set()
    truncated = False

    for current_file in _iter_repo_files(root):
        if current_file.suffix != ".py":
            continue
        try:
            source = current_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(current_file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        lines = source.splitlines()
        resolved_current = current_file.resolve()

        for node in ast.walk(tree):
            matches = False
            if isinstance(node, ast.Name) and node.id == name:
                matches = True
            elif isinstance(node, ast.Attribute) and node.attr == name:
                matches = True
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == name or alias.asname == name:
                        matches = True
                        break

            if not matches:
                continue

            lineno = getattr(node, "lineno", None)
            if lineno is None:
                continue
            if (
                definition_path is not None
                and resolved_current == definition_path
                and lineno == line
            ):
                continue

            if lineno <= len(lines):
                entry = f"{current_file}:{lineno} {lines[lineno - 1].strip()}"
                if entry not in seen:
                    seen.add(entry)
                    results.append(entry)
                    if len(results) >= _MAX_MATCHES:
                        truncated = True
                        break
        if truncated:
            break

    if not results:
        return f"No references found for '{name}'."

    output = "\n".join(results)
    if truncated:
        output += f"\n[Output truncated at {_MAX_MATCHES} references.]"
    return truncate_output(output)
