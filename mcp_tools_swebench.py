from mcp.server.fastmcp import FastMCP

from swebench_tools.filesystem import (
    read_file,
    edit_file,
    list_files,
)

from swebench_tools.code_search import (
    search_code,
    search_function_or_class_definition_in_code,
    find_references,
)

from swebench_tools.execution import (
    run_tests,
    get_patch,
    run_command,
)

mcp = FastMCP("SWE-bench")

mcp.tool()(read_file)
mcp.tool()(edit_file)
mcp.tool()(list_files)

mcp.tool()(search_code)
mcp.tool()(search_function_or_class_definition_in_code)
mcp.tool()(find_references)

mcp.tool()(run_tests)
mcp.tool()(get_patch)
mcp.tool()(run_command)

if __name__ == "__main__":
    mcp.run()