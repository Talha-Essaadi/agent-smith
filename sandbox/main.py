import sys
import json

from final_answer import final_answer, FinalAnswerSignal

result = {
    "called": False,
    "value": None
}

generated_code = sys.stdin.read()
namespace = {"final_answer": final_answer}

try:
    exec(generated_code, namespace)

except FinalAnswerSignal as exc:
    result["called"] = True
    result["value"] = str(exc.value)

finally:
    with open("/tmp/agent/result.json", "w") as f:
        json.dump(result, f)