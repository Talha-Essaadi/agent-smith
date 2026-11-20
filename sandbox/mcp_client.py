
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Tool


# Abdo Debug # This client supports tools only; resource and prompt discovery and calls are missing.
class MCPClient:
    """Manage one MCP server connection."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
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

        await self._connect(stdio_client(params))

    async def connect_http(self, url: str) -> None:
        """Connect via Streamable HTTP."""
        await self._connect(streamable_http_client(url))

    async def _connect(self, transport: Any) -> None:
        if self._connected:
            raise RuntimeError("Already connected to an MCP server")

        stack = AsyncExitStack()

        try:
            streams = await stack.enter_async_context(transport)

            read, write = streams[0], streams[1]

            session = await stack.enter_async_context(
                ClientSession(read, write)
            )

            await session.initialize()

        except BaseException:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        self._connected = True

    def _require_client(self) -> ClientSession:
        if not self._connected or self._session is None:
            raise RuntimeError("MCP client is not connected")

        return self._session

    async def list_tools(self) -> list[Tool]:
        """Discover tools exposed by the MCP server."""
        session = self._require_client()

        tools: list[Tool] = []
        cursor = None

        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(result.tools)

            cursor = result.nextCursor
            if cursor is None:
                break

        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """Call an MCP tool."""
        session = self._require_client()

        return await session.call_tool(
            name,
            arguments=arguments or {},
        )

    async def close(self) -> None:
        """Close the MCP connection."""
        stack = self._stack

        if stack is None:
            return

        try:
            await stack.aclose()
        finally:
            self._stack = None
            self._session = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
