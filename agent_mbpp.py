import argparse
import asyncio
from pathlib import Path
import shlex
import signal
import sys

from dotenv import load_dotenv

from agent import (
    AgentConfig,
    AgentOrchestrator,
    LLMClient,
    PromptBuilder,
    resolve_llm_settings,
)
from sandbox import MCPManager, Sandbox
from schemas import MBPPTaskInput, SandboxConfig, SolutionOutput


class MBPPCLI:
    def __init__(self) -> None:
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument(
            "--task-file",
            type=str,
            required=True,
            help="Path to the task file",
        )
        self.parser.add_argument(
            "--output",
            type=str,
            required=True,
            help="Path to the output file",
        )
        self.parser.add_argument(
            "--model-name",
            type=str,
            required=False,
            help="Name of the model to use (defaults to MODEL_NAME)",
        )
        self.parser.add_argument(
            "--provider-url",
            type=str,
            required=False,
            help="Base URL of the provider (defaults to PROVIDER_URL)",
        )
        self.parser.add_argument(
            "--env-file",
            type=str,
            required=False,
            help="Path to the provider API keys file",
        )
        self.parser.add_argument(
            "--max-iterations",
            type=int,
            required=False,
            default=None,
            help="Maximum number of iterations",
        )
        self.parser.add_argument(
            "--mcp-stdio",
            type=str,
            required=False,
            default=None,
            help="Command used to launch a local MCP server",
        )
        self.parser.add_argument(
            "--mcp-server",
            type=str,
            required=False,
            default=None,
            help="URL of a Streamable HTTP MCP server",
        )
        self.args = self.parser.parse_args()

    def _load_task(self) -> MBPPTaskInput:
        task_path = Path(self.args.task_file)
        return MBPPTaskInput.model_validate_json(
            task_path.read_text(encoding="utf-8")
        )

    def _load_env(self) -> None:
        if self.args.env_file:
            load_dotenv(self.args.env_file, override=True)
        else:
            load_dotenv(override=False)

    async def run(self) -> None:
        task: MBPPTaskInput | None = None
        sandbox: Sandbox | None = None
        manager: MCPManager | None = None
        system_prompt = ""
        solution_output: SolutionOutput | None = None

        current_task = asyncio.current_task()
        loop = asyncio.get_running_loop()

        def _handle_sigterm() -> None:
            if current_task is not None and not current_task.done():
                current_task.cancel()

        try:
            loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        except (NotImplementedError, RuntimeError):
            pass

        try:
            self._load_env()
            model_name, provider_url = resolve_llm_settings(
                self.args.model_name,
                self.args.provider_url,
            )
            task = self._load_task()

            llm_client = LLMClient(
                model_name=model_name,
                provider_url=provider_url,
                env_file=self.args.env_file
            )
            limits = AgentConfig().get_limits("mbpp", self.args.max_iterations)

            sandbox_config = SandboxConfig()
            manager = MCPManager()

            if self.args.mcp_stdio:
                parts = shlex.split(self.args.mcp_stdio)
                await manager.connect_stdio(
                    server_name="mbpp",
                    command=parts[0],
                    args=parts[1:],
                )
            elif self.args.mcp_server:
                await manager.connect_http(
                    server_name="mbpp",
                    url=self.args.mcp_server,
                )
            else:
                mcp_script = (
                    Path(__file__).resolve().parent / "mcp_tools_mbpp.py"
                )
                await manager.connect_stdio(
                    server_name="mbpp",
                    command=sys.executable,
                    args=[str(mcp_script)],
                )

            sandbox = Sandbox(sandbox_config, manager)
            system_prompt = PromptBuilder.build_mbpp_system_prompt(
                sandbox.get_manual("mbpp")
            )
            user_prompt = PromptBuilder.build_mbpp_user_prompt(task)

            orchestrator = AgentOrchestrator(llm_client, sandbox, limits)
            solution_output = await orchestrator.run(
                task_id=str(task.task_id),
                benchmark="mbpp",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except asyncio.CancelledError:
            task_id = str(task.task_id) if task else "unknown"
            solution_output = SolutionOutput(
                task_id=task_id,
                benchmark="mbpp",
                success=False,
                solution="",
                system_prompt=system_prompt,
                iterations=0,
                total_requests=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_time_seconds=0.0,
                error="Terminated by signal",
            )
        except Exception as e:
            # Build a minimal failure output so we always produce valid JSON
            task_id = str(task.task_id) if task else "unknown"
            solution_output = SolutionOutput(
                task_id=task_id,
                benchmark="mbpp",
                success=False,
                solution="",
                system_prompt=system_prompt,
                iterations=0,
                total_requests=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_time_seconds=0.0,
                error=str(e),
            )
        finally:
            try:
                if solution_output is not None:
                    output_path = Path(self.args.output)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        solution_output.model_dump_json(indent=2),
                        encoding="utf-8",
                    )
            finally:
                if manager is not None:
                    try:
                        await manager.close()
                    except Exception:
                        pass
                if sandbox is not None:
                    try:
                        sandbox.close()
                    except Exception:
                        pass


def main() -> None:
    cli = MBPPCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
