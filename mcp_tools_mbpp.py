
import json
import subprocess
import sys
import argparse

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("mbpp")


@mcp.tool()
def run_tests(code: str, test_list: list[str]) -> str:
    """
    Run a Python solution against MBPP test assertions.

    Args:
        code: Python solution to evaluate.
        test_list: List of Python test assertions.

    Returns:
        JSON string containing success and output.
    """
    test_script = (
        code
        + "\n\n"
        + "\n".join(test_list)
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", test_script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        return json.dumps({
            "success": result.returncode == 0,
            "output": (
                result.stdout + result.stderr
            ),
        })

    except subprocess.TimeoutExpired:
        return json.dumps({
            "success": False,
            "output": "Test execution timed out.",
        })

    except Exception as exc:
        return json.dumps({
            "success": False,
            "output": str(exc),
        })



if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="stdio",
        )

        args = parser.parse_args()

        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        print("\nInterrupted.")