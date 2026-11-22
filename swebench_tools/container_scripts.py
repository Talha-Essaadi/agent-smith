_CONTAINER_READ_SCRIPT = """
import json, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
path = Path(req["filepath"]).resolve()
try:
    path.relative_to(root)
except ValueError:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "PermissionError",
            "error": f"Access denied: {req['filepath']}"
        }
    ))
    sys.exit(0)

if not path.is_file():
    print(json.dumps(
        {
            "ok": False,
            "error_type": "FileNotFoundError",
            "error": f"File not found: {req['filepath']}"
        }
    ))
    sys.exit(0)

try:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
except OSError as exc:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "RuntimeError",
            "error": str(exc)
        }
    ))
    sys.exit(0)

start = req["start_line"]
end = req["end_line"]
if start > len(lines):
    print(json.dumps(
        {
            "ok": True,
            "result": f"File contains only {len(lines)} lines."
        }
    ))
    sys.exit(0)

end = len(lines) if end is None else min(end, len(lines))
out = [f"{ln}: {lines[ln - 1]}" for ln in range(start, end + 1)]
print(json.dumps({"ok": True, "result": "\\n".join(out)}))
"""

_CONTAINER_EDIT_SCRIPT = """
import ast, json, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
path = Path(req["filepath"]).resolve()
try:
    path.relative_to(root)
except ValueError:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "PermissionError",
            "error": f"Access denied: {req['filepath']}"
        }
    ))
    sys.exit(0)

if not path.is_file():
    print(json.dumps(
        {
            "ok": False,
            "error_type": "FileNotFoundError",
            "error": f"File not found: {req['filepath']}"
        }
    ))
    sys.exit(0)

old_str = req["old_str"]
new_str = req["new_str"]
content = path.read_text(encoding="utf-8")
occurrences = content.count(old_str)
if occurrences == 0:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "ValueError",
            "error": "old_str was not found in the file"
        }
    ))
    sys.exit(0)
if occurrences > 1:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "ValueError",
            "error": (
                f"old_str appears {occurrences} times."
                " Provide a more specific string."
            )
        }
    ))
    sys.exit(0)

updated = content.replace(old_str, new_str, 1)
path.write_text(updated, encoding="utf-8")

msg = f"Successfully edited {req['display_path']}"
if str(path).endswith(".py"):
    try:
        ast.parse(updated, filename=str(path))
    except SyntaxError as exc:
        msg += (
            "\\n[WARNING: SyntaxError introduced "
            f"at line {exc.lineno}: {exc.msg}]"
        )

print(json.dumps({"ok": True, "result": msg}))
"""

_CONTAINER_LIST_SCRIPT = """
import fnmatch, json, os, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
base = Path(req["directory"]).resolve()
try:
    base.relative_to(root)
except ValueError:
    print(json.dumps(
        {
            "ok": False,
            "error_type": "PermissionError",
            "error": f"Access denied: {req['directory']}"
        }
    ))
    sys.exit(0)

if not base.exists():
    print(json.dumps(
        {
            "ok": False,
            "error_type": "FileNotFoundError",
            "error": f"Directory not found: {req['directory']}"
        }
    ))
    sys.exit(0)
if not base.is_dir():
    print(json.dumps(
        {
            "ok": False,
            "error_type": "NotADirectoryError",
            "error": f"Not a directory: {req['directory']}"
        }
    ))
    sys.exit(0)

pattern = req["pattern"] or "*"
results = []
for dirpath, dirnames, filenames in os.walk(base):
    dirnames[:] = [d for d in dirnames if d != ".git"]
    for fname in filenames:
        item = Path(dirpath) / fname
        try:
            item.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        rel_dir = item.relative_to(base).as_posix()
        if (fnmatch.fnmatch(fname, pattern)
                or fnmatch.fnmatch(rel_dir, pattern)):
            results.append(item.relative_to(root).as_posix())

results.sort()
if not results:
    out = f"No files matching '{pattern}' found in '{req['display_dir']}'."
else:
    out = "\\n".join(results)
print(json.dumps({"ok": True, "result": out}))
"""

_CONTAINER_SEARCH_CODE_SCRIPT = """
import fnmatch, json, os, re, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
pattern = req["pattern"]
file_pattern = req["file_pattern"] or "*"
max_matches = req["max_matches"]

try:
    regex = re.compile(pattern)
except re.error:
    regex = None

results = []
truncated = False
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames if d != ".git")
    for fname in sorted(filenames):
        filepath = Path(dirpath) / fname
        try:
            filepath.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        rel = filepath.relative_to(root).as_posix()
        if (not fnmatch.fnmatch(fname, file_pattern)
                and not fnmatch.fnmatch(rel, file_pattern)):
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
                if len(results) >= max_matches:
                    truncated = True
                    break
        if truncated:
            break
    if truncated:
        break

if not results:
    out = f"No matches found for '{pattern}'."
else:
    out = "\\n".join(results)
    if truncated:
        out += (
            f"\\n[Output truncated at {max_matches} matches."
            " Narrow your pattern or file_pattern.]"
        )
print(json.dumps({"ok": True, "result": out}))
"""

_CONTAINER_SEARCH_DEF_SCRIPT = """
import ast, json, os, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
name = req["name"]
results = []

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames if d != ".git")
    for fname in sorted(filenames):
        if not fname.endswith(".py"):
            continue
        filepath = Path(dirpath) / fname
        try:
            filepath.resolve().relative_to(root)
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (ValueError, SyntaxError, UnicodeDecodeError, OSError):
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if (isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ) and node.name == name):
                line_text = (
                    lines[node.lineno - 1].strip()
                    if node.lineno <= len(lines)
                    else f"{name}"
                )
                results.append(f"{filepath}:{node.lineno} {line_text}")

out = (
    f"No definition found for '{name}'."
    if not results
    else "\\n".join(results)
)
print(json.dumps({"ok": True, "result": out}))
"""

_CONTAINER_FIND_REFS_SCRIPT = """
import ast, json, os, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
name = req["name"]
def_path = Path(req["filepath"]).resolve() if req["filepath"] else None
def_line = req["line"]
max_matches = req["max_matches"]

if def_path is not None:
    try:
        def_path.relative_to(root)
    except ValueError:
        print(json.dumps({"ok": False, "error_type": "PermissionError", "error": f"Access denied: {req['filepath']}"}))
        sys.exit(0)
    if not def_path.is_file():
        print(json.dumps({"ok": False, "error_type": "FileNotFoundError", "error": f"File not found: {req['filepath']}"}))
        sys.exit(0)

results = []
seen = set()
truncated = False

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames if d != ".git")
    for fname in sorted(filenames):
        if not fname.endswith(".py"):
            continue
        filepath = Path(dirpath) / fname
        try:
            resolved = filepath.resolve()
            resolved.relative_to(root)
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (ValueError, SyntaxError, UnicodeDecodeError, OSError):
            continue
        lines = source.splitlines()
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
            if def_path is not None and resolved == def_path and lineno == def_line:
                continue
            if lineno <= len(lines):
                entry = f"{filepath}:{lineno} {lines[lineno - 1].strip()}"
                if entry not in seen:
                    seen.add(entry)
                    results.append(entry)
                    if len(results) >= max_matches:
                        truncated = True
                        break
        if truncated:
            break
    if truncated:
        break

if not results:
    out = f"No references found for '{name}'."
else:
    out = "\\n".join(results)
    if truncated:
        out += f"\\n[Output truncated at {max_matches} references.]"
print(json.dumps({"ok": True, "result": out}))
"""
