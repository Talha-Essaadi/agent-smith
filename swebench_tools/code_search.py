
import ast
import fnmatch
from pathlib import Path


TESTBED_ROOT = Path("/testbed").resolve()


def _resolve_path(path: str) -> Path:
    """Resolve a path and prevent access outside /testbed."""
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = TESTBED_ROOT / candidate

    resolved = candidate.resolve()

    try:
        resolved.relative_to(TESTBED_ROOT)
    except ValueError:
        raise PermissionError(f"Access denied: {path}")

    return resolved


def _get_python_files(directory: Path):
    """Return Python files inside a directory, excluding external symlinks."""
    for filepath in directory.rglob("*.py"):
        try:
            resolved = filepath.resolve()
            resolved.relative_to(TESTBED_ROOT)
        except (ValueError, OSError):
            continue

        if filepath.is_file():
            yield filepath


# ---------------------------------------------------------
# 1. Search source code
# ---------------------------------------------------------

def search_code(pattern: str, file_pattern: str = "*") -> str:
    """
    Search for a text pattern in repository files.

    Args:
        pattern: Text to search for.
        file_pattern: File glob, e.g. '*.py', '*.c', '*.h'.

    Returns:
        Matching lines in grep-like format.
    """
    if not pattern:
        raise ValueError("pattern cannot be empty")

    results = []

    for filepath in TESTBED_ROOT.rglob("*"):
        try:
            filepath.resolve().relative_to(TESTBED_ROOT)
        except (ValueError, OSError):
            continue

        if not filepath.is_file():
            continue

        relative_path = filepath.relative_to(TESTBED_ROOT).as_posix()

        if not fnmatch.fnmatch(filepath.name, file_pattern) and not fnmatch.fnmatch(
            relative_path, file_pattern
        ):
            continue

        try:
            content = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if pattern in line:
                results.append(
                    f"{filepath}:{line_number} {line}"
                )

    if not results:
        return f"No matches found for '{pattern}'."

    return "\n".join(results)


# ---------------------------------------------------------
# 2. Find function or class definitions
# ---------------------------------------------------------

def search_function_or_class_definition_in_code(name: str) -> str:
    """
    Search Python files for function, async function, or class definitions.

    Uses AST rather than text matching, so calls such as foo()
    are not mistaken for definitions.
    """
    if not name:
        raise ValueError("name cannot be empty")

    results = []

    for filepath in _get_python_files(TESTBED_ROOT):
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                if node.name == name:
                    kind = (
                        "class" if isinstance(node, ast.ClassDef)
                        else "function"
                    )

                    results.append(
                        f"{filepath}:{node.lineno} "
                        f"{kind} {node.name}"
                    )

    if not results:
        return f"No definition found for '{name}'."

    return "\n".join(results)


# ---------------------------------------------------------
# 3. Find symbol references
# ---------------------------------------------------------

def find_references(name: str, filepath: str, line: int) -> str:
    """
    Find references to a Python symbol throughout the repository.

    Args:
        name: Symbol name, e.g. 'execute_task'.
        filepath: File containing the symbol's definition.
        line: Definition's starting line.

    Returns:
        Matching source lines, excluding the definition itself.
    """
    if not name or not name.isidentifier():
        raise ValueError("name must be a valid Python identifier")

    if line < 1:
        raise ValueError("line must be >= 1")

    definition_path = _resolve_path(filepath)

    if not definition_path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    results = []

    for current_file in _get_python_files(TESTBED_ROOT):
        try:
            source = current_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(current_file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        source_lines = source.splitlines()

        for node in ast.walk(tree):
            matches = False

            # Example: execute_task()
            if isinstance(node, ast.Name) and node.id == name:
                matches = True

            # Example: agent.execute_task()
            elif isinstance(node, ast.Attribute) and node.attr == name:
                matches = True

            # Example: from module import execute_task
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == name:
                        matches = True
                    elif alias.asname == name:
                        matches = True

            if not matches:
                continue

            node_line = getattr(node, "lineno", None)

            if node_line is None:
                continue

            # Ignore the original definition location.
            if (
                current_file.resolve() == definition_path
                and node_line == line
            ):
                continue

            if node_line <= len(source_lines):
                results.append(
                    f"{current_file}:{node_line} "
                    f"{source_lines[node_line - 1].strip()}"
                )

    if not results:
        return f"No references found for '{name}'."

    return "\n".join(sorted(set(results)))
