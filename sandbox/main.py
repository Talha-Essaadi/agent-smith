
import sys
import json
import traceback

from final_answer import final_answer, FinalAnswerSignal


result = {
    "called": False,
    "value": None,
}

try:
    # 1. Wait for one JSON message from DockerRunner
    print("[DEBUG] Waiting for code...", file=sys.stderr, flush=True)

    message = json.loads(sys.stdin.readline())

    # 2. Extract the generated Python code
    generated_code = message["code"]

    print("[DEBUG] Code received", file=sys.stderr, flush=True)

    # 3. Prepare execution namespace
    namespace = {
        "final_answer": final_answer,
    }

    # 4. Execute generated code
    print("[DEBUG] Executing code...", file=sys.stderr, flush=True)

    try:
        exec(generated_code, namespace)

    except FinalAnswerSignal as exc:
        result["called"] = True
        result["value"] = str(exc.value)

    print("[DEBUG] Execution finished", file=sys.stderr, flush=True)

except Exception:
    # Show the actual Python error in Docker logs
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

finally:
    # 5. Save execution result
    with open("/tmp/agent/result.json", "w") as f:
        json.dump(result, f)
