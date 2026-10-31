
import ast


class ImportGuard:

    def __init__(self, authorized_imports: list[str]):
        self.authorized_imports = authorized_imports

    def _is_allowed(self, module: str) -> bool:
        for allowed in self.authorized_imports:
            if allowed == module:
                return True

            if allowed.endswith(".*"):
                prefix = allowed[:-2]
                if module == prefix or module.startswith(prefix + "."):
                    return True

        return False

    def validate(self, code: str) -> None:
        tree = ast.parse(code)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self._is_allowed(alias.name):
                        raise ImportError(
                            f"Unauthorized import: {alias.name}"
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    raise ImportError("Relative imports are not allowed")

                module = node.module or ""

                if not self._is_allowed(module):
                    raise ImportError(
                        f"Unauthorized import: {module}"
                    )
