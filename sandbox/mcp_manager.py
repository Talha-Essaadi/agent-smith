from typing import Any

import httpx
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    Prompt,
    ReadResourceResult,
    Resource,
)

from sandbox.exceptions import MCPConnectionError
from sandbox.mcp_client import MCPClient
from sandbox.tool_registry import ToolRegistry


def _is_connection_error(exc: BaseException) -> bool:
    """Check whether an exception contains an HTTP connection error."""
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_connection_error(child) for child in exc.exceptions)
    return False


class MCPManager:
    """Manage MCP server connections and registered tools."""

    def __init__(self) -> None:
        self.clients: dict[str, MCPClient] = {}
        self.registry = ToolRegistry()
        self._resources: dict[str, list[Resource]] = {}
        self._prompts: dict[str, list[Prompt]] = {}

    async def _discover_all(self, server_name: str, client: MCPClient) -> None:
        tools = await client.list_tools()
        self.registry.register_many(server_name, tools)
        self._resources[server_name] = await client.list_resources()
        self._prompts[server_name] = await client.list_prompts()

    async def connect_stdio(
        self,
        server_name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Connect to a local MCP server via stdio."""
        if server_name in self.clients:
            raise ValueError(f"Server '{server_name}' is already connected")

        client = MCPClient()
        try:
            await client.connect_stdio(command=command, args=args, env=env)
            await self._discover_all(server_name, client)
            self.clients[server_name] = client
        except BaseException:
            self.registry.unregister_server(server_name)
            self._resources.pop(server_name, None)
            self._prompts.pop(server_name, None)
            try:
                await client.close()
            except Exception:
                pass
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
            await client.connect_http(url)
            await self._discover_all(server_name, client)
            self.clients[server_name] = client
        except BaseException as exc:
            self.registry.unregister_server(server_name)
            self._resources.pop(server_name, None)
            self._prompts.pop(server_name, None)
            try:
                await client.close()
            except Exception:
                pass

            if _is_connection_error(exc):
                raise MCPConnectionError(
                    f"Cannot connect to MCP server at {url}"
                ) from None
            raise

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """Execute a registered MCP tool."""
        tool = self.registry.get_tool(name)
        client = self.clients.get(tool.server_name)
        if client is None:
            raise RuntimeError(
                f"MCP server '{tool.server_name}' is not connected"
            )

        return await client.call_tool(
            name=tool.original_name,
            arguments=arguments or {},
        )

    def list_tools(self):
        """Return all registered MCP tools."""
        return self.registry.list_tools()

    def list_resources(self) -> list[dict[str, Any]]:
        """Return all discovered MCP resources across connected servers."""
        items: list[dict[str, Any]] = []
        for server_name, resources in self._resources.items():
            for res in resources:
                items.append({
                    "server": server_name,
                    "uri": str(res.uri),
                    "name": res.name,
                    "description": res.description or "",
                    "mimeType": res.mimeType or "",
                })
        return items

    async def read_resource(self, uri: str) -> ReadResourceResult:
        """Read an MCP resource by URI from the server that exposes it."""
        for server_name, resources in self._resources.items():
            if any(str(res.uri) == uri for res in resources):
                client = self.clients.get(server_name)
                if client is not None:
                    return await client.read_resource(uri)

        # Fallback: try connected servers directly (supports URI templates).
        last_error: Exception | None = None
        for client in self.clients.values():
            try:
                return await client.read_resource(uri)
            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            f"Resource '{uri}' not found"
            + (f": {last_error}" if last_error else "")
        )

    def list_prompts(self) -> list[dict[str, Any]]:
        """Return all discovered MCP prompts across connected servers."""
        items: list[dict[str, Any]] = []
        for server_name, prompts in self._prompts.items():
            for prompt in prompts:
                items.append({
                    "server": server_name,
                    "name": prompt.name,
                    "description": prompt.description or "",
                    "arguments": [
                        {
                            "name": arg.name,
                            "description": arg.description or "",
                            "required": bool(arg.required),
                        }
                        for arg in (prompt.arguments or [])
                    ],
                })
        return items

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> GetPromptResult:
        """Retrieve an MCP prompt by name."""
        for server_name, prompts in self._prompts.items():
            if any(p.name == name for p in prompts):
                client = self.clients.get(server_name)
                if client is not None:
                    return await client.get_prompt(name, arguments=arguments)

        raise KeyError(f"Unknown MCP prompt: {name}")

    def list_servers(self) -> list[str]:
        """Return the names of connected MCP servers."""
        return list(self.clients.keys())

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
            self._resources.pop(server_name, None)
            self._prompts.pop(server_name, None)

    async def close(self) -> None:
        """Close all MCP connections and unregister their tools."""
        try:
            for server_name in list(self.clients.keys()):
                try:
                    await self.disconnect(server_name)
                except Exception:
                    pass
        finally:
            self.clients.clear()
            self._resources.clear()
            self._prompts.clear()
