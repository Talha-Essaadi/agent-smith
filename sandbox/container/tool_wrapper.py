
from collections.abc import Callable
from typing import Any


def create_tool_wrapper(
    tool_name: str,
    call_tool: Callable[..., Any],
) -> Callable[..., Any]:
    """Create a Python callable for one MCP tool."""

    def wrapper(**kwargs: Any) -> Any:
        return call_tool(
            name=tool_name,
            arguments=kwargs,
        )

    wrapper.__name__ = tool_name
    wrapper.__doc__ = f"MCP tool: {tool_name}"

    return wrapper


def create_tool_namespace(
    tool_names: list[str],
    call_tool: Callable[..., Any],
) -> dict[str, Callable[..., Any]]:
    """Create wrappers for all discovered tools."""

    namespace = {}

    for name in tool_names:
        namespace[name] = create_tool_wrapper(
            tool_name=name,
            call_tool=call_tool,
        )

    return namespace
