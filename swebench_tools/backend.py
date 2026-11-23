import json
import os
import posixpath
import subprocess
from pathlib import Path
from typing import Any


MAX_OUTPUT_CHARS = 50_000


def is_docker_mode() -> bool:
    """Return True when tools should
     execute inside a SWE-bench Docker container."""
    return bool(os.environ.get("SWE_CONTAINER_ID", "").strip())


def get_container_id() -> str:
    cid = os.environ.get("SWE_CONTAINER_ID", "").strip()
    if not cid:
        raise RuntimeError("SWE_CONTAINER_ID is not set")
    return cid


def get_testbed_root() -> Path:
    """Resolve repository root from TESTBED_PATH (defaults to /testbed)."""
    return Path(os.environ.get("TESTBED_PATH", "/testbed")).resolve()


def resolve_local_path(raw_path: str) -> Path:
    """Resolve a path inside TESTBED_ROOT for local/moulinette isolated mode.

    Accepts:
      - relative paths (resolved against TESTBED_ROOT)
      - `/testbed` or `/testbed/...` (mapped onto TESTBED_ROOT)
      - absolute paths already inside TESTBED_ROOT
    """
    root = get_testbed_root()
    candidate = Path(raw_path)

    if candidate.is_absolute():
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(root)
            return resolved_candidate
        except ValueError:
            pass

        # Support Docker-style /testbed/... paths
        # when TESTBED_PATH is elsewhere.
        posix_norm = posixpath.normpath(raw_path)
        if posix_norm == "/testbed":
            return root
        if posix_norm.startswith("/testbed/"):
            rel = posix_norm[len("/testbed/"):]
            resolved = (root / rel).resolve()
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                pass

        raise PermissionError(f"Access denied: '{raw_path}' is outside {root}")

    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PermissionError(
            f"Access denied: '{raw_path}' is outside {root}"
        ) from None
    return resolved


def resolve_container_path(raw_path: str) -> str:
    """Resolve and validate a POSIX path inside /testbed in the container."""
    raw = raw_path or "/testbed"
    if posixpath.isabs(raw):
        norm = posixpath.normpath(raw)
    else:
        norm = posixpath.normpath(posixpath.join("/testbed", raw))

    if norm != "/testbed" and not norm.startswith("/testbed/"):
        raise PermissionError(
            f"Access denied: '{raw_path}' is outside /testbed"
        )
    return norm


def truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate long output while preserving
     both head and tail (e.g. pytest summary)."""
    if len(text) <= max_chars:
        return text
    head_len = max_chars // 3
    tail_len = max_chars - head_len
    omitted = len(text) - max_chars
    return (
        f"{text[:head_len]}"
        f"\n\n[Output truncated: {omitted} "
        "characters omitted due to size limits. "
        f"Use more specific queries or smaller ranges.]\n\n"
        f"{text[-tail_len:]}"
    )


def docker_exec_python(
    script: str,
    payload: dict[str, Any],
    timeout: int = 30,
) -> Any:
    """Execute a stdlib Python snippet
     inside the SWE-bench container via JSON stdin."""
    cid = get_container_id()
    launcher = (
        'PY=$([ -x /opt/miniconda3/envs/testbed/bin/python ] '
        '&& echo /opt/miniconda3/envs/testbed/bin/python '
        '|| command -v python3 || command -v python); '
        'exec "$PY" -c "$1"'
    )

    try:
        proc = subprocess.run(
            [
                "docker", "exec", "-i", "-w", "/testbed",
                cid, "bash", "-c", launcher, "_", script
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Container tool operation timed out after {timeout}s"
        ) from exc

    stdout = (proc.stdout or "").strip()
    if not stdout:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"Container tool failed (exit {proc.returncode}):"
            f" {stderr or 'no output'}"
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON from container tool: {stdout[:300]}"
        ) from exc

    if not data.get("ok"):
        err_type = data.get("error_type", "RuntimeError")
        err_msg = data.get("error", "Unknown container tool error")
        exc_map = {
            "ValueError": ValueError,
            "FileNotFoundError": FileNotFoundError,
            "NotADirectoryError": NotADirectoryError,
            "PermissionError": PermissionError,
        }
        raise exc_map.get(err_type, RuntimeError)(err_msg)

    return data.get("result")


def run_shell(
    command: str,
    workdir: str = "/testbed",
    timeout: int = 120,
    script_stdin: str | None = None,
) -> tuple[str, str, int, bool]:
    """Run a bash command either locally in
     TESTBED_PATH or inside the Docker container.

    Returns:
        (stdout, stderr, exit_code, timed_out)
    """
    if is_docker_mode():
        cid = get_container_id()
        cwd = resolve_container_path(workdir)
        conda_prefix = (
            'if [ -d /opt/miniconda3/envs/testbed/bin ]; then '
            'export PATH="/opt/miniconda3/envs/testbed/bin:'
            '/opt/miniconda3/bin:$PATH"; '
            'fi; '
        )

        if script_stdin is not None:
            runner_cmd = (
                f"{conda_prefix}"
                f"if command -v timeout >/dev/null 2>&1; then "
                f"timeout -k 5 {timeout} bash; "
                f"else bash; fi"
            )
            cmd = [
                "docker", "exec", "-i", "-w",
                cwd, cid, "bash", "-c", runner_cmd
            ]
            stdin_data = script_stdin
        else:
            runner_cmd = (
                f"{conda_prefix}"
                f"if command -v timeout >/dev/null 2>&1; then "
                f'timeout -k 5 {timeout} bash -c "$1"; '
                f'else bash -c "$1"; fi'
            )
            cmd = [
                "docker", "exec", "-w", cwd, cid,
                "bash", "-c", runner_cmd, "_", command
            ]
            stdin_data = None

        try:
            proc = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
                check=False,
            )
            timed_out = proc.returncode == 124
            return (
                proc.stdout or "",
                proc.stderr or "",
                proc.returncode,
                timed_out
            )
        except subprocess.TimeoutExpired as exc:
            out = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            err = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            return out, err, 124, True

    # Local / moulinette isolated mode
    cwd_path = resolve_local_path(workdir)
    if not cwd_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {workdir}")

    cmd = ["bash"] if script_stdin is not None else ["bash", "-c", command]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd_path),
            input=script_stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.stdout or "", proc.stderr or "", proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        out = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        err = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return out, err, 124, True
