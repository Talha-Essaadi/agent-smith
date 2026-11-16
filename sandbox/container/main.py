
import sys
import json
import traceback
import io
from contextlib import redirect_stdout, redirect_stderr

from final_answer import final_answer, FinalAnswerSignal
from ipc_bridge import IPCBridge
from tool_wrapper import create_tool_namespace


result = {
    "called": False,
    "value": None,
    "stdout": "",
    "stderr": "",
    "error": None,
}

protocol_in = sys.stdin
protocol_out = sys.stdout

try:
    print("[DEBUG] Waiting for code...", file=sys.stderr, flush=True)

    message = json.loads(protocol_in.readline())

    generated_code = message["code"]
    tool_names = message.get("tools", [])

    # Create container-side IPC bridge
    bridge = IPCBridge(protocol_in, protocol_out)

    # Dynamically inject discovered MCP tools
    namespace = create_tool_namespace(
        tool_names=tool_names,
        call_tool=bridge.call_tool,
    )

    namespace["final_answer"] = final_answer

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    print("[DEBUG] Executing code...", file=sys.stderr, flush=True)

    try:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            exec(generated_code, namespace)

    except FinalAnswerSignal as exc:
        result["called"] = True
        result["value"] = str(exc.value)

    finally:
        result["stdout"] = stdout_buffer.getvalue()
        result["stderr"] = stderr_buffer.getvalue()

    print("[DEBUG] Execution finished", file=sys.stderr, flush=True)

except Exception:
    result["error"] = traceback.format_exc()
    print(result["error"], file=sys.stderr, flush=True)

finally:
    with open("/tmp/agent/result.json", "w") as f:
        json.dump(result, f)
