from collections.abc import Callable
from typing import Any


def create_tool_wrapper(
    tool_name: str,
    call_tool: Callable[..., Any],
    parameter_names: list[str],
) -> Callable[..., Any]:
    """Create an MCP tool wrapper supporting positional
     and keyword arguments."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if len(args) > len(parameter_names):
            raise TypeError(
                f"{tool_name} accepts at most "
                f"{len(parameter_names)} positional arguments"
            )

        arguments = dict(zip(parameter_names, args))

        for key, value in kwargs.items():
            if key in arguments:
                raise TypeError(
                    f"{tool_name} got multiple values for argument '{key}'"
                )
            arguments[key] = value

        return call_tool(name=tool_name, arguments=arguments)

    wrapper.__name__ = tool_name
    wrapper.__doc__ = f"MCP tool: {tool_name}"
    return wrapper


def create_tool_namespace(
    tools: list[dict[str, Any]],
    call_tool: Callable[..., Any],
) -> dict[str, Callable[..., Any]]:
    """Create callable Python wrappers for all discovered MCP tools."""
    namespace: dict[str, Callable[..., Any]] = {}

    for tool in tools:
        name = tool["name"]
        input_schema = tool.get("inputSchema") or {}
        parameter_names = list(input_schema.get("properties", {}).keys())

        namespace[name] = create_tool_wrapper(
            tool_name=name,
            call_tool=call_tool,
            parameter_names=parameter_names,
        )

    return namespace
