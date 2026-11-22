import argparse
import asyncio
import json
import shlex
import sys
import os
from pathlib import Path

from aioconsole import ainput, aprint

from sandbox.exceptions import MCPConnectionError
from sandbox.mcp_manager import MCPManager
from sandbox.sandbox import Sandbox
from schemas.sandbox import SandboxConfig


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
        raise FileNotFoundError(f"Configuration file not found: {path}")

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

        command = sys.executable if parts[0] in ("python", "python3") else parts[0]
        await manager.connect_stdio(
            server_name="stdio",
            command=command,
            args=parts[1:],
            env={
                key: os.environ[key]
                for key in ("TESTBED_PATH", "SWE_CONTAINER_ID")
                if key in os.environ
            },
        )
        return True

    if args.mcp_server:
        await manager.connect_http(
            server_name="remote",
            url=args.mcp_server,
        )
        return True

    return False


def display_tools(manager: MCPManager) -> None:
    """Display registered MCP tools, resources, and prompts."""
    tools = manager.list_tools()
    resources = manager.list_resources()
    prompts = manager.list_prompts()

    if not tools:
        print("No MCP tools registered.")
    else:
        print(f"Available MCP tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}")
            if tool.description:
                print(f"    {tool.description}")

    if resources:
        print(f"Available MCP resources ({len(resources)}):")
        for res in resources:
            print(f"  - {res['uri']} ({res['name']})")

    if prompts:
        print(f"Available MCP prompts ({len(prompts)}):")
        for prompt in prompts:
            print(f"  - {prompt['name']}")


async def interactive_loop(
    sandbox: Sandbox,
    manager: MCPManager,
) -> None:
    """Read Python code from the terminal and execute it."""
    interactive = sys.stdin.isatty()
    if interactive:
        print(
            "Agent Smith Sandbox "
            "(type 'exit' or Ctrl+D to quit, ':tools' to list MCP tools)"
        )

    while True:
        try:
            code = (
                await ainput("sandbox> ")
                if interactive else await asyncio.to_thread(sys.stdin.read)
            )
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break

        command = code.strip()
        if interactive and command in ("exit", "exit()", ":exit", ":quit"):
            break

        if interactive and command == ":tools":
            display_tools(manager)
            continue

        if not command:
            if not interactive:
                break
            continue

        try:
            result = await sandbox.execute(code)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break

        if result.stdout:
            if interactive:
                await aprint(
                    result.stdout,
                    end="" if result.stdout.endswith("\n") else "\n"
                )
            else:
                print(
                    result.stdout,
                    end="" if result.stdout.endswith("\n") else "\n"
                )

        if result.stderr:
            if interactive:
                await aprint(
                    result.stderr,
                    end="" if result.stderr.endswith("\n") else "\n",
                    use_stderr=True,
                )
            else:
                print(
                    result.stderr,
                    end="" if result.stderr.endswith("\n") else "\n",
                    file=sys.stderr
                )

        if result.error:
            print(f"Error: {result.error}")

        if result.timed_out:
            print("Execution timed out.")

        if result.truncated:
            print("Output truncated.")

        if result.is_final_answer:
            print(f"Final answer: {result.final_answer_value}")

        if not interactive:
            break


async def async_main() -> None:
    """Initialize sandbox, MCP manager, and interactive CLI."""
    args = parse_args()
    config = load_config(args.config)
    manager = MCPManager()
    runner = Sandbox(config, manager)

    try:
        connected = await connect_mcp(manager, args)
        if connected and sys.stdin.isatty():
            display_tools(manager)

        await interactive_loop(runner, manager)

    finally:
        try:
            await manager.close()
        finally:
            runner.close()


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except MCPConnectionError as exc:
        print(
            "\n[ERROR] Failed to connect to MCP server.\n"
            "The server may be stopped or unreachable.\n"
            "Check the URL, port, and server status.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except Exception as exc:
        print(f"Execution error: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
