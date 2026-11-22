_CONTAINER_READ_SCRIPT = """
import json, sys
from pathlib import Path

req = json.loads(sys.stdin.read())
root = Path("/testbed").resolve()
path = Path(req["filepath"]).resolve()
try:
    path.relative_to(root)
except ValueError:
    print(json.dumps({"ok": False, "error_type": "PermissionError", "error": f"Access denied: {req['filepath']}"}))
    sys.exit(0)

if not path.is_file():
    print(json.dumps({"ok": False, "error_type": "FileNotFoundError", "error": f"File not found: {req['filepath']}"}))
    sys.exit(0)

try:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
except OSError as exc:
    print(json.dumps({"ok": False, "error_type": "RuntimeError", "error": str(exc)}))
    sys.exit(0)

start = req["start_line"]
end = req["end_line"]
if start > len(lines):
    print(json.dumps({"ok": True, "result": f"File contains only {len(lines)} lines."}))
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
    print(json.dumps({"ok": False, "error_type": "PermissionError", "error": f"Access denied: {req['filepath']}"}))
    sys.exit(0)

if not path.is_file():
    print(json.dumps({"ok": False, "error_type": "FileNotFoundError", "error": f"File not found: {req['filepath']}"}))
    sys.exit(0)

old_str = req["old_str"]
new_str = req["new_str"]
content = path.read_text(encoding="utf-8")
occurrences = content.count(old_str)
if occurrences == 0:
    print(json.dumps({"ok": False, "error_type": "ValueError", "error": "old_str was not found in the file"}))
    sys.exit(0)
if occurrences > 1:
    print(json.dumps({"ok": False, "error_type": "ValueError", "error": f"old_str appears {occurrences} times. Provide a more specific string."}))
    sys.exit(0)

updated = content.replace(old_str, new_str, 1)
path.write_text(updated, encoding="utf-8")

msg = f"Successfully edited {req['display_path']}"
if str(path).endswith(".py"):
    try:
        ast.parse(updated, filename=str(path))
    except SyntaxError as exc:
        msg += f"\\n[WARNING: SyntaxError introduced at line {exc.lineno}: {exc.msg}]"

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
    print(json.dumps({"ok": False, "error_type": "PermissionError", "error": f"Access denied: {req['directory']}"}))
    sys.exit(0)

if not base.exists():
    print(json.dumps({"ok": False, "error_type": "FileNotFoundError", "error": f"Directory not found: {req['directory']}"}))
    sys.exit(0)
if not base.is_dir():
    print(json.dumps({"ok": False, "error_type": "NotADirectoryError", "error": f"Not a directory: {req['directory']}"}))
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
        if fnmatch.fnmatch(fname, pattern) or fnmatch.fnmatch(rel_dir, pattern):
            results.append(item.relative_to(root).as_posix())

results.sort()
if not results:
    out = f"No files matching '{pattern}' found in '{req['display_dir']}'."
else:
    out = "\\n".join(results)
print(json.dumps({"ok": True, "result": out}))
"""
