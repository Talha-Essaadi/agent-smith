
from mcp.server.fastmcp import FastMCP
from swebench_tools import (
    read_file,
    edit_file,
    list_files,
    search_code,
    search_function_or_class_definition_in_code,
    find_references,
    run_tests,
    get_patch,
    run_command,
    pwd,
)
import argparse



# Create the MCP server
mcp = FastMCP("swebench")


# -----------------------------
# Filesystem tools
# -----------------------------

mcp.tool()(pwd)
mcp.tool()(read_file)
mcp.tool()(edit_file)
mcp.tool()(list_files)


# -----------------------------
# Code search tools
# -----------------------------

mcp.tool()(search_code)
mcp.tool()(search_function_or_class_definition_in_code)
mcp.tool()(find_references)


# -----------------------------
# Execution tools
# -----------------------------

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
        print("\nInterrupted.")