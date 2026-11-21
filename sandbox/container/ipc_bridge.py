import json
from typing import Any, TextIO


class IPCBridge:
    """Line-delimited JSON IPC bridge between container code
     and host runner."""

    def __init__(
        self,
        protocol_in: TextIO,
        protocol_out: TextIO,
    ) -> None:
        self._protocol_in = protocol_in
        self._protocol_out = protocol_out
        self._next_id = 0

    def send_event(self, payload: dict[str, Any]) -> None:
        self._protocol_out.write(json.dumps(payload) + "\n")
        self._protocol_out.flush()

    def _request(self, req_type: str, payload: dict[str, Any]) -> Any:
        self._next_id += 1
        request_id = self._next_id

        message = {"type": req_type, "id": request_id, **payload}
        self.send_event(message)

        line = self._protocol_in.readline()
        if not line:
            raise RuntimeError("IPC connection closed")

        response = json.loads(line)
        if response.get("id") != request_id:
            raise RuntimeError(
                "Unexpected IPC response id: expected"
                f" {request_id!r}, got {response!r}"
            )

        if not response.get("success"):
            raise RuntimeError(response.get("error", "MCP request failed"))

        return response.get("result")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._request(
            "tool_call",
            {"name": name, "arguments": arguments},
        )

    def list_resources(self) -> Any:
        return self._request("mcp_list_resources", {})

    def read_resource(self, uri: str) -> Any:
        return self._request("mcp_read_resource", {"uri": uri})

    def list_prompts(self) -> Any:
        return self._request("mcp_list_prompts", {})

    def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        return self._request(
            "mcp_get_prompt",
            {"name": name, "arguments": arguments or {}},
        )
