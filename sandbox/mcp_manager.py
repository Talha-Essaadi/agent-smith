
from typing import Any

from mcp.types import CallToolResult

from sandbox.mcp_client import MCPClient
from sandbox.tool_registry import ToolRegistry


class MCPManager:
    """Manage MCP server connections and registered tools."""

    def __init__(self) -> None:
        self.clients: dict[str, MCPClient] = {}
        self.registry = ToolRegistry()

    async def connect_stdio(
        self,
        server_name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Connect to a local MCP server via stdio."""

        if server_name in self.clients:
            raise ValueError(
                f"Server '{server_name}' is already connected"
            )

        client = MCPClient()

        try:
            # Connect to the MCP server.
            await client.connect_stdio(
                command=command,
                args=args,
                env=env,
            )

            # Discover tools.
            tools = await client.list_tools()

            # Register tools.
            self.registry.register_many(
                server_name,
                tools,
            )

            # Store connected client.
            self.clients[server_name] = client

        except BaseException:
            self.registry.unregister_server(server_name)
            try:
                await client.close()
            finally:
                raise

    async def connect_http(
        self,
        server_name: str,
        url: str,
    ) -> None:
        """Connect to an MCP server via Streamable HTTP."""

        if server_name in self.clients:
            raise ValueError(
                f"Server '{server_name}' is already connected"
            )

        client = MCPClient()

        try:
            # Connect to the MCP server.
            await client.connect_http(url)

            # Discover tools.
            tools = await client.list_tools()

            # Register tools.
            self.registry.register_many(
                server_name,
                tools,
            )

            # Store connected client.
            self.clients[server_name] = client

        except BaseException:
            self.registry.unregister_server(server_name)
            try:
                await client.close()
            finally:
                raise

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """Execute a registered MCP tool."""

        # Find the registered tool.
        tool = self.registry.get_tool(name)

        # Find the client that owns the tool.
        client = self.clients.get(tool.server_name)

        if client is None:
            raise RuntimeError(
                f"MCP server '{tool.server_name}' is not connected"
            )

        # Execute using the original MCP tool name.
        return await client.call_tool(
            name=tool.original_name,
            arguments=arguments or {},
        )

    async def disconnect(
        self,
        server_name: str,
    ) -> None:
        """Disconnect one MCP server and unregister its tools."""

        client = self.clients.pop(server_name, None)

        if client is None:
            raise ValueError(
                f"Server '{server_name}' is not connected"
            )

        try:
            await client.close()
        finally:
            self.registry.unregister_server(server_name)

    async def close(self) -> None:
        """Disconnect all MCP servers and clear the registry."""

        errors = []

        # Close in reverse connection order.
        for server_name in reversed(list(self.clients)):
            try:
                await self.disconnect(server_name)
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise ExceptionGroup(
                "Failed to close some MCP connections",
                errors,
            )

    def list_tools(self):
        """Return all registered MCP tools."""

        return self.registry.list_tools()

    def list_servers(self) -> list[str]:
        """Return the names of connected MCP servers."""

        return list(self.clients.keys())
