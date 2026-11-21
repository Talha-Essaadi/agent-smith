import builtins
import io
import json
import os
import sys
import traceback
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from final_answer import FinalAnswerSignal, final_answer
from ipc_bridge import IPCBridge
from tool_wrapper import create_tool_namespace
from restrictions import (
    _REAL_IMPORT,
    _REAL_OPEN,
    _REAL_GETATTR,
    _REAL_SETATTR,
    _REAL_DELATTR,
    _BLOCKED_BUILTINS,
    _BLOCKED_ATTRS,
)


class _StreamingWriter(io.TextIOBase):
    """Captures output locally and streams chunks to host for partial timeout output."""

    def __init__(self, stream_name: str, bridge: IPCBridge) -> None:
        self._stream_name = stream_name
        self._bridge = bridge
        self._chunks: list[str] = []

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if data:
            self._chunks.append(data)
            self._bridge.send_event({
                "type": "stream",
                "stream": self._stream_name,
                "data": data,
            })
        return len(data)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return "".join(self._chunks)


def _is_import_allowed(module: str, authorized_imports: list[str]) -> bool:
    for allowed in authorized_imports:
        if allowed == module:
            return True
        if allowed.endswith(".*"):
            prefix = allowed[:-2]
            if module == prefix or module.startswith(prefix + "."):
                return True
    return False


def _make_safe_import(authorized_imports: list[str]):
    def _safe_import(
        name: str,
        globals_: Any = None,
        locals_: Any = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if level != 0:
            raise ImportError("Relative imports are not allowed")

        if not _is_import_allowed(name, authorized_imports):
            raise ImportError(f"Unauthorized import: {name}")

        module = _REAL_IMPORT(name, globals_, locals_, fromlist, level)

        if fromlist:
            for item in fromlist:
                if item == "*":
                    continue
                attr = _REAL_GETATTR(module, item, None)
                if isinstance(attr, types.ModuleType):
                    sub_name = _REAL_GETATTR(attr, "__name__", f"{name}.{item}")
                    if not _is_import_allowed(sub_name, authorized_imports):
                        raise ImportError(f"Unauthorized import: {sub_name}")

        return module

    return _safe_import


def _make_safe_open(allowed_directories: list[str]):
    allowed_roots = [Path(os.path.realpath(d)) for d in allowed_directories]

    def _safe_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, int):
            raise PermissionError("Opening raw file descriptors is not allowed")

        raw_path = os.fspath(file)
        if isinstance(raw_path, bytes):
            raw_path = raw_path.decode("utf-8", errors="surrogateescape")

        resolved = Path(os.path.realpath(os.path.abspath(raw_path)))

        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return _REAL_OPEN(str(resolved), *args, **kwargs)
            except ValueError:
                continue

        raise PermissionError(
            f"Access denied: '{raw_path}' is outside allowed directories "
            f"{allowed_directories}"
        )

    return _safe_open


def _make_blocked_builtin(name: str):
    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError(f"Builtin '{name}' is restricted in the sandbox")

    _blocked.__name__ = name
    return _blocked


def _safe_getattr(obj: Any, name: str, *default: Any) -> Any:
    if isinstance(name, str) and name in _BLOCKED_ATTRS:
        raise PermissionError(f"Access to attribute '{name}' is restricted")
    return _REAL_GETATTR(obj, name, *default)


def _safe_setattr(obj: Any, name: str, value: Any) -> None:
    if isinstance(name, str) and name in _BLOCKED_ATTRS:
        raise PermissionError(f"Modification of attribute '{name}' is restricted")
    _REAL_SETATTR(obj, name, value)


def _safe_delattr(obj: Any, name: str) -> None:
    if isinstance(name, str) and name in _BLOCKED_ATTRS:
        raise PermissionError(f"Deletion of attribute '{name}' is restricted")
    _REAL_DELATTR(obj, name)


def _build_safe_builtins(
    authorized_imports: list[str],
    allowed_directories: list[str],
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for name in dir(builtins):
        if name in _BLOCKED_BUILTINS:
            safe[name] = _make_blocked_builtin(name)
        else:
            safe[name] = _REAL_GETATTR(builtins, name)

    safe["__import__"] = _make_safe_import(authorized_imports)
    safe["open"] = _make_safe_open(allowed_directories)
    safe["getattr"] = _safe_getattr
    safe["setattr"] = _safe_setattr
    safe["delattr"] = _safe_delattr
    return safe


def main() -> None:
    protocol_in = sys.stdin
    protocol_out = sys.stdout
    bridge = IPCBridge(protocol_in, protocol_out)

    # First message initializes the persistent sandbox session.
    init_line = protocol_in.readline()
    if not init_line:
        return

    init_msg = json.loads(init_line)
    authorized_imports: list[str] = init_msg.get("authorized_imports", [])
    allowed_directories: list[str] = init_msg.get("allowed_directories", [])

    user_namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__builtins__": _build_safe_builtins(
            authorized_imports,
            allowed_directories,
        ),
        "final_answer": final_answer,
        "list_mcp_resources": bridge.list_resources,
        "read_mcp_resource": bridge.read_resource,
        "list_mcp_prompts": bridge.list_prompts,
        "get_mcp_prompt": bridge.get_prompt,
    }
    registered_tool_names: set[str] = set()

    bridge.send_event({"type": "ready"})

    while True:
        raw_line = protocol_in.readline()
        if not raw_line:
            break

        message = json.loads(raw_line)
        msg_type = message.get("type")

        if msg_type == "shutdown":
            break

        if msg_type != "exec":
            continue

        code = message.get("code", "")
        tools = message.get("tools", [])

        # Refresh MCP tool wrappers while preserving user variables.
        new_wrappers = create_tool_namespace(tools=tools, call_tool=bridge.call_tool)
        for old_name in registered_tool_names - set(new_wrappers.keys()):
            user_namespace.pop(old_name, None)
        user_namespace.update(new_wrappers)
        registered_tool_names = set(new_wrappers.keys())

        # Ensure sandbox built-in controls cannot be overwritten permanently.
        user_namespace["final_answer"] = final_answer

        stdout_writer = _StreamingWriter("stdout", bridge)
        stderr_writer = _StreamingWriter("stderr", bridge)

        result: dict[str, Any] = {
            "type": "exec_result",
            "called": False,
            "value": None,
            "stdout": "",
            "stderr": "",
            "error": None,
            "resource_limit_exceeded": False,
        }

        try:
            with redirect_stdout(stdout_writer), redirect_stderr(stderr_writer):
                compiled = compile(code, "<sandbox>", "exec")
                exec(compiled, user_namespace)
        except FinalAnswerSignal as exc:
            result["called"] = True
            result["value"] = str(exc.value)
        except MemoryError:
            result["error"] = "MemoryError: Execution exceeded memory limit."
            result["resource_limit_exceeded"] = True
        except (KeyboardInterrupt, SystemExit) as exc:
            result["stdout"] = stdout_writer.getvalue()
            result["stderr"] = stderr_writer.getvalue()
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["control_exception"] = type(exc).__name__
            bridge.send_event(result)
            break
        except Exception:
            result["error"] = traceback.format_exc()
        finally:
            result["stdout"] = stdout_writer.getvalue()
            result["stderr"] = stderr_writer.getvalue()

        bridge.send_event(result)


if __name__ == "__main__":
    main()
