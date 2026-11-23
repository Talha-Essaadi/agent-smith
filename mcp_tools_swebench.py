import argparse
import sys

from mcp.server.fastmcp import FastMCP

from swebench_tools import (
    edit_file,
    find_references,
    get_patch,
    list_files,
    read_file,
    run_command,
    run_tests,
    search_code,
    search_function_or_class_definition_in_code,
)


mcp = FastMCP("swebench", log_level="WARNING")

# File system tools
mcp.tool()(read_file)
mcp.tool()(edit_file)
mcp.tool()(list_files)

# Code search tools
mcp.tool()(search_code)
mcp.tool()(search_function_or_class_definition_in_code)
mcp.tool()(find_references)

# Execution tools
mcp.tool()(run_tests)
mcp.tool()(get_patch)
mcp.tool()(run_command)


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
        print("\nInterrupted.", file=sys.stderr)
