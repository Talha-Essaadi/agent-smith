from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, Tool


class MCPClient:
    """Manage one MCP server connection."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._connected = False

    async def connect_stdio(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Connect to a local MCP server via stdio."""
        params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        await self._connect(params)

    async def connect_http(self, url: str) -> None:
        """Connect to an MCP server via Streamable HTTP."""
        await self._connect(url)

    async def _connect(self, server: Any) -> None:
        if self._connected:
            raise RuntimeError("Already connected to an MCP server")

        client = Client(server)

        # Enter the SDK-managed connection.
        await client.__aenter__()

        self._client = client
        self._connected = True

    def _require_client(self) -> Client:
        if not self._connected or self._client is None:
            raise RuntimeError("MCP client is not connected")

        return self._client

    async def list_tools(self) -> list[Tool]:
        """Discover tools exposed by the MCP server."""
        client = self._require_client()

        tools = []
        cursor = None

        while True:
            result = await client.list_tools(cursor=cursor)
            tools.extend(result.tools)

            cursor = result.next_cursor
            if cursor is None:
                break

        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """Call a tool by name."""
        client = self._require_client()

        return await client.call_tool(
            name,
            arguments or {},
        )

    async def close(self) -> None:
        """Close the MCP connection."""
        if self._client is None:
            return

        client = self._client

        try:
            await client.__aexit__(None, None, None)
        finally:
            self._client = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
