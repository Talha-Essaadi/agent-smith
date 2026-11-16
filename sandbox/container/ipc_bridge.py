import json
import sys
from typing import Any, TextIO


class IPCBridge:
    def __init__(
        self,
        protocol_in: TextIO,
        protocol_out: TextIO,
    ):
        self.protocol_in = protocol_in
        self.protocol_out = protocol_out
        self.next_id = 0

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.next_id += 1
        request_id = self.next_id

        request = {
            "type": "tool_call",
            "id": request_id,
            "name": name,
            "arguments": arguments,
        }

        self.protocol_out.write(json.dumps(request) + "\n")
        self.protocol_out.flush()

        line = self.protocol_in.readline()

        if not line:
            raise RuntimeError("IPC connection closed")

        response = json.loads(line)

        if (
            response.get("type") != "tool_result"
            or response.get("id") != request_id
        ):
            raise RuntimeError("Unexpected IPC response")

        if not response.get("success"):
            raise RuntimeError(response.get("error", "MCP tool failed"))

        return response["result"]