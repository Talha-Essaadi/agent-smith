from typing import Any

from sandbox.mcp_manager import MCPManager
from sandbox.runner import DockerRunner
from schemas import BaseSandbox, ExecutionResult, SandboxConfig


_JSON_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
    "null": "None",
}


def _schema_to_py_type(prop: dict[str, Any]) -> str:
    if "anyOf" in prop:
        types = [_schema_to_py_type(sub) for sub in prop["anyOf"]]
        return " | ".join(dict.fromkeys(types))

    raw_type = prop.get("type")
    if isinstance(raw_type, list):
        return " | ".join(_JSON_TYPE_MAP.get(t, "Any") for t in raw_type)

    if raw_type == "array":
        items = prop.get("items")
        if isinstance(items, dict):
            return f"list[{_schema_to_py_type(items)}]"
        return "list"

    return _JSON_TYPE_MAP.get(str(raw_type), "Any")


def _format_tool_signature(name: str, input_schema: dict[str, Any]) -> str:
    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    params: list[str] = []

    for param_name, prop in properties.items():
        py_type = _schema_to_py_type(prop if isinstance(prop, dict) else {})
        if param_name in required:
            params.append(f"{param_name}: {py_type}")
        elif isinstance(prop, dict) and "default" in prop:
            params.append(f"{param_name}: {py_type} = {prop['default']!r}")
        else:
            params.append(f"{param_name}: {py_type} = None")

    return f"{name}({', '.join(params)})"


def _summarize_description(description: str) -> str:
    lines = [
        line.strip()
        for line in description.strip().splitlines()
        if line.strip()
    ]
    if not lines:
        return "No description provided."
    return lines[0]


class Sandbox(BaseSandbox):
    """High-level sandbox facade wrapping DockerRunner and MCPManager."""

    def __init__(
        self,
        config: SandboxConfig,
        mcp_manager: MCPManager,
    ) -> None:
        self.config = config
        self.mcp_manager = mcp_manager
        self._runner = DockerRunner(config, mcp_manager)

    async def execute(self, code: str) -> ExecutionResult:
        tools = self.mcp_manager.list_tools()
        return await self._runner.run(code, tools)

    def get_manual(self, type: str | None = None) -> str:
        """Dynamically generate a concise manual
         of sandbox limits and MCP capabilities."""
        if type is None or type not in ("mbpp", "swebench"):
            raise ValueError(
                f"Unknown benchmark type: {type}. "
                "Expected 'mbpp' or 'swebench'."
            )

        config = self.config
        sections: list[str] = [
            (
                "Sandbox Environment:\n"
                f"- Allowed imports: {', '.join(config.authorized_imports)}\n"
                "- Allowed directories: "
                f"{', '.join(config.allowed_directories)}"
                f"\n- Limits: {config.max_execution_time_seconds}s per step, "
                f"{config.max_memory_mb} MB RAM, no network access,"
                " restricted builtins.\n"
                "- Variables persist across steps."
            )
        ]

        # Dynamically document all tools
        # from whichever MCP server(s) are connected
        tools = self.mcp_manager.list_tools()
        tool_lines = ["MCP Tools (callable directly as Python functions):"]
        if not tools:
            tool_lines.append("- None connected.")
        else:
            for tool in tools:
                sig = _format_tool_signature(tool.name, tool.inputSchema)
                desc = _summarize_description(tool.description)
                tool_lines.append(f"- `{sig}`: {desc}")
        sections.append("\n".join(tool_lines))

        # Include MCP resources only if the connected server exposes any
        resources = self.mcp_manager.list_resources()
        if resources:
            res_lines = [
                "MCP Resources (use `list_mcp_resources()`"
                " and `read_mcp_resource(uri)`):"
            ]
            for res in resources:
                desc = f" — {res['description']}" if res["description"] else ""
                res_lines.append(f"- `{res['uri']}` ({res['name']}){desc}")
            sections.append("\n".join(res_lines))

        # Include MCP prompts only if the connected server exposes any.
        prompts = self.mcp_manager.list_prompts()
        if prompts:
            prompt_lines = [
                "MCP Prompts (use `list_mcp_prompts()`"
                " and `get_mcp_prompt(name, arguments)`):"
            ]
            for prompt in prompts:
                desc = (
                    f" — {prompt['description']}"
                    if prompt["description"]
                    else ""
                )
                prompt_lines.append(f"- `{prompt['name']}`{desc}")
            sections.append("\n".join(prompt_lines))

        sections.append(
            "Built-in Completion Function:\n"
            "- `final_answer(value: str)`: "
            "Submit your final solution and end the loop."
        )

        return "\n\n".join(sections)

    def close(self) -> None:
        """Clean up Docker sandbox resources."""
        self._runner.close()
