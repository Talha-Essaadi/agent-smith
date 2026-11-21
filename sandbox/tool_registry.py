from dataclasses import dataclass
from mcp.types import Tool


@dataclass
class RegisteredTool:
    name: str
    server_name: str
    original_name: str
    description: str
    inputSchema: dict


class ToolRegistry:
    """Stores dynamically discovered MCP tools under clean
     Python-callable names."""

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, server_name: str, tool: Tool) -> None:
        """Register a tool discovered from an MCP server.

        Uses the tool's original MCP name directly unless a different server
        already registered a tool with the same name (in which case the tool
        is namespaced as `<server_name>__<tool_name>`).
        """
        existing = self._tools.get(tool.name)
        if existing is None:
            registered_name = tool.name
        elif existing.server_name == server_name:
            raise ValueError(
                f"Tool '{tool.name}' is already "
                f"registered for server '{server_name}'"
            )
        else:
            registered_name = f"{server_name}__{tool.name}"
            if registered_name in self._tools:
                raise ValueError(
                    f"Tool '{registered_name}' is already registered"
                )

        self._tools[registered_name] = RegisteredTool(
            name=registered_name,
            server_name=server_name,
            original_name=tool.name,
            description=tool.description or "",
            inputSchema=tool.inputSchema,
        )

    def register_many(
        self,
        server_name: str,
        tools: list[Tool],
    ) -> None:
        """Register multiple tools from one MCP server."""
        for tool in tools:
            self.register(server_name, tool)

    def get_tool(self, name: str) -> RegisteredTool:
        """Retrieve a registered tool by name (or qualified `server__name`)."""
        if name in self._tools:
            return self._tools[name]

        for tool in self._tools.values():
            if f"{tool.server_name}__{tool.original_name}" == name:
                return tool

        raise KeyError(f"Unknown MCP tool: {name}")

    def list_tools(self) -> list[RegisteredTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def unregister_server(self, server_name: str) -> None:
        """Remove all tools belonging to a disconnected server."""
        self._tools = {
            name: tool
            for name, tool in self._tools.items()
            if tool.server_name != server_name
        }
