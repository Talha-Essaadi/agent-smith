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
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, server_name: str, tool: Tool) -> None:
        """Register a tool discovered from an MCP server."""

        # Avoid collisions between tools from different servers
        qualified_name = f"{server_name}__{tool.name}"

        if qualified_name in self._tools:
            raise ValueError(
                f"Tool '{qualified_name}' is already registered"
            )

        self._tools[qualified_name] = RegisteredTool(
            name=qualified_name,
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
        """Retrieve a registered tool by its qualified name."""

        if name not in self._tools:
            raise KeyError(f"Unknown MCP tool: {name}")

        return self._tools[name]

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