import os
import ast
import fnmatch
import builtins
from typing import List, Callable, Any, Dict

from schemas import SandboxConfig
from .import_restriction import ALLOWED_DUNDERS, BLOCKED_BUILTINS


class SandboxSecurity:
    def __init__(self, config: SandboxConfig):
        self.config = config
        self.allowed_dirs = [
            os.path.realpath(d)
            for d in config.allowed_directories
        ]

    def validate_ast(self, code: str) -> None:
        parsed_code = ast.parse(code)
        for node in ast.walk(parsed_code):
            if isinstance(node, ast.Attribute):
                if (node.attr.startswith("__") and node.attr.endswith("__")
                        and node.attr not in ALLOWED_DUNDERS):
                    raise PermissionError(
                        f"Access to restricted attribute '{node.attr}'"
                        " is blocked by sandbox")

            if isinstance(node, ast.Name):
                if (node.id.startswith("__") and node.id.endswith("__")
                        and node.id not in ALLOWED_DUNDERS):
                    raise PermissionError(
                        f"Access to restricted name '{node.id}'"
                        " is blocked by sandbox")

    def make_safe_import(self) -> Callable:
        def _is_allowed(module: str) -> bool:
            return any(fnmatch.fnmatch(module, pat)
                       for pat in self.config.authorized_imports)

        def _safe_import(name: str, globals=None,
                         locals=None, fromlist=(),
                         level: int = 0):

            if level != 0:
                raise ImportError("Relative imports are not allowed in sandbox")

            if not _is_allowed(name):
                if not fromlist or not all(
                    item != "*" and _is_allowed(f"{name}.{item}")
                    for item in fromlist
                ):
                    raise ImportError(f"Import of '{name}' "
                                    "is blocked by sandbox policy")

            return builtins.__import__(name, globals, locals, fromlist, level)

        return _safe_import

    def make_safe_open(self) -> Callable:
        def is_allowed(file: str):
            return (file in self.allowed_directories
                    or any(file.startswith(dir.rstrip("/") + os.sep)
                           for dir in self.allowed_directories))

        def _safe_open(file, mode="r", *args, **kwargs):
            if isinstance(file, int):
                raise PermissionError("Opening raw file descriptors "
                                      "is blocked")

            try:
                target = os.path.realpath(os.fspath(file))
            except TypeError:
                raise PermissionError(f"Invalid file path type: {type(file)}")

            if not is_allowed(target):
                raise PermissionError(f"Filesystem access to '{file}' "
                                      "is outside allowed directories")

            return builtins.open(file, mode, *args, **kwargs)

        return _safe_open

    def build_safe_builtins(self) -> Dict[str, Any]:
        # Remove the blacklisted builtins and add the safe ones
        safe_builtins = {
            name: obj
            for name, obj in builtins.__dict__.items()
            if name not in BLOCKED_BUILTINS
            and (not name.startswith("_") or name in ("__build_class__", "__name__", "__doc__"))
        }

        # Inject safe replacements
        safe_builtins["__import__"] = self.make_safe_import()
        safe_builtins["open"] = self.make_safe_open()

        # Standard safe singleton constants
        safe_builtins["True"] = True
        safe_builtins["False"] = False
        safe_builtins["None"] = None
        safe_builtins["Ellipsis"] = Ellipsis

        return safe_builtins


if __name__ == "__main__":
    config = SandboxConfig()
    security = SandboxSecurity(config)

    tests = [
        # Should pass: normal code
        ("print('hello')", True),
        ("x = 1 + 2", True),
        ("import math\nmath.sqrt(4)", True),
        ("[x**2 for x in range(10)]", True),

        # Should block: dangerous builtins
        ("eval('1+1')", False),
        ("exec('print(1)')", False),
        ("compile('x=1', '', 'exec')", False),
        ("open('/etc/passwd')", False),
        ("__import__('os')", False),

        # Should block: dunder access (outside allowed set)
        ("x.__class__.__bases__", False),
        ("x.__subclasses__()", False),

        # Should pass: allowed dunders
        ("class Foo:\n    def __init__(self): pass", True),
        ("x.__str__()", True),
        ("x.__repr__()", True),
    ]

    print(f"{'TEST':<50} {'EXPECT':<10} {'RESULT':<10}")
    print("-" * 70)

    for code, should_pass in tests:
        label = code.replace("\n", "\\n")[:48]
        try:
            security.validate_ast(code)
            passed = True
        except Exception as e:
            passed = False

        status = "✅" if passed == should_pass else "❌"
        print(f"{status} {label:<48} {str(should_pass):<10} {'pass' if passed else 'block'}")

    # --- Test make_safe_import ---
    print()
    print(f"{'IMPORT TEST':<50} {'EXPECT':<10} {'RESULT':<10}")
    print("-" * 70)

    safe_import = SandboxSecurity.make_safe_import(config.authorized_imports)

    import_tests = [
        # (name, fromlist, should_pass)
        # Should pass: base module allowed
        ("math", (), True),
        ("collections", (), True),
        ("itertools", (), True),
        ("json", (), True),

        # Should pass: fromlist with allowed submodule (collections.*)
        ("collections", ("deque",), True),
        ("collections", ("OrderedDict",), True),
        ("math", ("sqrt", "pi"), True),

        # Should block: base module not allowed
        ("os", (), False),
        ("subprocess", (), False),
        ("socket", (), False),

        # Should block: fromlist with blocked submodule
        ("os", ("system",), False),
        ("os", ("path",), False),
        ("subprocess", ("Popen",), False),

        # Should pass: wildcard in fromlist is skipped
        ("math", ("*",), True),
    ]

    for name, fromlist, should_pass in import_tests:
        if fromlist:
            label = f"from {name} import {', '.join(fromlist)}"[:48]
        else:
            label = f"import {name}"[:48]
        try:
            safe_import(name, fromlist=fromlist)
            passed = True
        except ImportError:
            passed = False

        status = "✅" if passed == should_pass else "❌"
        print(f"{status} {label:<48} {str(should_pass):<10} {'pass' if passed else 'block'}")

    # --- Test make_safe_open ---
    import tempfile
    from pathlib import Path

    print()
    print(f"{'OPEN TEST':<50} {'EXPECT':<10} {'RESULT':<10}")
    print("-" * 70)

    with tempfile.TemporaryDirectory() as temp_dir:
        allowed_dir = os.path.realpath(temp_dir)
        safe_open = SandboxSecurity.make_safe_open([allowed_dir])

        allowed_file = os.path.join(allowed_dir, "test.txt")
        with open(allowed_file, "w") as f:
            f.write("allowed content")

        os.makedirs(os.path.join(allowed_dir, "subdir"), exist_ok=True)

        outside_dir = tempfile.gettempdir()
        prefix_attack_path = allowed_dir + "_fake" + os.sep + "file.txt"

        open_tests = [
            # Allowed access
            (allowed_file, "r", True, "Read inside allowed directory"),
            (Path(allowed_file), "r", True, "Pathlib inside allowed directory"),
            (os.path.join(allowed_dir, "new.txt"), "w", True, "Create in allowed directory"),
            (os.path.join(allowed_dir, "subdir", "file.txt"), "w", True, "Subdir in allowed directory"),

            # Blocked access: outside directories
            ("/etc/passwd", "r", False, "Read /etc/passwd"),
            ("/etc/shadow", "r", False, "Read /etc/shadow"),

            # Blocked access: traversal attempts
            (os.path.join(allowed_dir, "..", "escape.txt"), "w", False, "Path traversal escape"),

            # Blocked access: prefix spoofing
            (prefix_attack_path, "w", False, "Prefix matching attack"),

            # Blocked access: raw file descriptor / invalid types
            (0, "r", False, "Raw integer file descriptor"),
            (None, "r", False, "None as file path"),
        ]

        for target, mode, should_pass, label in open_tests:
            try:
                res = safe_open(target, mode)
                if hasattr(res, "close"):
                    res.close()
                passed = True
            except PermissionError:
                passed = False
            except Exception:
                passed = False

            status = "✅" if passed == should_pass else "❌"
            print(f"{status} {label:<48} {str(should_pass):<10} {'pass' if passed else 'block'}")

    # --- Test build_safe_builtins ---
    print()
    print(f"{'SAFE BUILTINS TEST':<50} {'EXPECT':<10} {'RESULT':<10}")
    print("-" * 70)

    safe_b = security.build_safe_builtins(config)
    builtins_tests = [
        ("print in safe_builtins", True, "print" in safe_b),
        ("len in safe_builtins", True, "len" in safe_b),
        ("ValueError in safe_builtins", True, "ValueError" in safe_b),
        ("Exception in safe_builtins", True, "Exception" in safe_b),
        ("__import__ is customized", True, callable(safe_b.get("__import__"))),
        ("open is customized", True, callable(safe_b.get("open"))),
        ("eval is excluded", False, "eval" in safe_b),
        ("exec is excluded", False, "exec" in safe_b),
        ("compile is excluded", False, "compile" in safe_b),
    ]

    for label, expected, actual in builtins_tests:
        status = "✅" if actual == expected else "❌"
        print(f"{status} {label:<48} {str(expected):<10} {str(actual):<10}")



