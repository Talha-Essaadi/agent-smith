
import argparse
import asyncio
import json
import shlex
from pathlib import Path

from schemas.sandbox import SandboxConfig
from sandbox.mcp_manager import MCPManager
from sandbox.sandbox import Sandbox
from aioconsole import ainput


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        prog="sandbox",
        description="Agent Smith interactive Docker sandbox",
    )

    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to sandbox JSON configuration file",
    )

    mcp_group = parser.add_mutually_exclusive_group()

    mcp_group.add_argument(
        "--mcp-stdio",
        type=str,
        help="Command used to launch a local MCP server",
    )

    mcp_group.add_argument(
        "--mcp-server",
        type=str,
        help="URL of a Streamable HTTP MCP server",
    )

    return parser.parse_args()


def load_config(path: str | None) -> SandboxConfig:
    """Load and validate the sandbox configuration."""

    if path is None:
        return SandboxConfig()

    config_path = Path(path)

    if not config_path.is_file():
        raise FileNotFoundError(
            f"Configuration file not found: {path}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return SandboxConfig.model_validate(data)


async def connect_mcp(
    manager: MCPManager,
    args: argparse.Namespace,
) -> bool:
    """Connect to MCP server and register its tools."""

    if args.mcp_stdio:
        parts = shlex.split(args.mcp_stdio)

        if not parts:
            raise ValueError("Empty MCP stdio command")

        await manager.connect_stdio(
            server_name="stdio",
            command=parts[0],
            args=parts[1:],
        )

    elif args.mcp_server:
        await manager.connect_http(
            server_name="remote",
            url=args.mcp_server,
        )

    else:
        return False

    return True


def display_tools(manager: MCPManager) -> None:
    """Display registered MCP tools."""

    tools = manager.registry.list_tools()

    if not tools:
        print("No MCP tools registered.")
        return

    print(f"Available MCP tools ({len(tools)}):")

    for tool in tools:
        print(f"  - {tool.name}")
        if tool.description:
            print(f"    {tool.description}")


async def interactive_loop(
    sandbox: Sandbox,
    manager: MCPManager,
) -> None:
    """Read Python code from the terminal and execute it."""

    print("Agent Smith Sandbox")
    print("Type :exit to quit")
    print("Type :tools to list MCP tools")
    print()

    while True:
        try:
            # Read input directly without creating a worker thread.
            code = await ainput("sandbox> ")

        except (EOFError, KeyboardInterrupt):
            print("\nInterrupted.")
            break

        command = code.strip()

        if command in (":exit", ":quit"):
            break

        if command == ":tools":
            display_tools(manager)
            continue

        if not command:
            continue

        print("Executing code...")

        try:
            # Docker SDK operations are blocking.
            result = await asyncio.to_thread(
                sandbox.execute,
                code,
            )

        except asyncio.CancelledError:
            print("\nExecution interrupted.")
            raise

        except KeyboardInterrupt:
            print("\nInterrupted.")
            break

        except Exception as exc:
            print(f"Execution error: {exc}")
            continue

        if result.stdout:
            print(result.stdout, end="")

        if result.stderr:
            print(result.stderr, end="")

        if result.error:
            print(f"\nError: {result.error}")

        if result.timed_out:
            print("\nExecution timed out.")

        if result.truncated:
            print("\nOutput truncated.")

        if result.is_final_answer:
            print(
                "\nFinal answer:",
                result.final_answer_value,
            )
            break


async def async_main() -> None:
    """Initialize sandbox, MCP manager, and interactive CLI."""

    args = parse_args()

    config = load_config(args.config)

    manager = MCPManager()

    runner = Sandbox(config, manager)


    try:
        connected = await connect_mcp(manager, args)

        if connected:
            tools = manager.registry.list_tools()

            print(
                f"Connected to MCP server "
                f"({len(tools)} tools registered)"
            )

            for tool in tools:
                print(f"  - {tool.name}")

        await interactive_loop(runner, manager)

    finally:
        await manager.close()


def main() -> None:
    """Synchronous entry point for pyproject.toml."""

    try:
        asyncio.run(async_main())

    except KeyboardInterrupt:
        print("\nInterrupted.")

    except Exception as exc:
        print(f"Sandbox error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
