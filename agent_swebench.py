import argparse
import asyncio
from pathlib import Path
import shlex
import sys
from dotenv import load_dotenv

from agent import AgentConfig, resolve_llm_settings
from agent import PromptBuilder, AgentOrchestrator, LLMClient
from sandbox import Sandbox, MCPManager
from schemas import SWEBenchTaskInput, SolutionOutput, SandboxConfig


class SWEBenchCLI:
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument(
            "--task-file", type=str,
            required=True, help="Path to the task file"
        )
        self.parser.add_argument(
            "--output", type=str,
            required=True, help="Path to the output file"
        )
        self.parser.add_argument(
            "--model-name", type=str,
            required=False,
            help="Name of the model to use (defaults to MODEL_NAME)",
        )
        self.parser.add_argument(
            "--provider-url", type=str,
            required=False,
            help="Base URL of the provider (defaults to PROVIDER_URL)",
        )
        self.parser.add_argument(
            "--env-file", type=str,
            required=False, help="Path to the provider API keys file"
        )
        self.parser.add_argument(
            "--max-iterations", type=int, required=False,
            default=None, help="Maximum number of iterations"
        )
        self.parser.add_argument(
            "--mcp-stdio", type=str, required=False, default=None,
            help="Command used to launch a local MCP server",
        )
        self.parser.add_argument(
            "--mcp-server", type=str, required=False, default=None,
            help="URL of a Streamable HTTP MCP server",
        )
        self.args = self.parser.parse_args()

    def _load_task(self) -> SWEBenchTaskInput:
        task_file = self.args.task_file
        with open(task_file, "r") as f:
            task = f.read()
        task = SWEBenchTaskInput.model_validate_json(task)
        return task

    async def run(self) -> None:
        task = None
        sandbox = None
        mcp_manager = None
        solution_output: SolutionOutput | None = None
        try:
            load_dotenv(self.args.env_file, override=True)
            model_name, provider_url = resolve_llm_settings(
                self.args.model_name, self.args.provider_url,
            )
            # Load task
            task = self._load_task()
            # Initialize LLM client
            llm_client = LLMClient(model_name=model_name,
                                   provider_url=provider_url,
                                   env_file=self.args.env_file)
            # Get limits
            limits = AgentConfig().get_limits("swebench",
                                              self.args.max_iterations)
            # Initialize sandbox and MCP manager
            sandbox_config = SandboxConfig()
            mcp_manager = MCPManager()

            if self.args.mcp_stdio:
                parts = shlex.split(self.args.mcp_stdio)
                await mcp_manager.connect_stdio(
                    server_name="swebench",
                    command=parts[0],
                    args=parts[1:],
                )
            elif self.args.mcp_server:
                await mcp_manager.connect_http(
                    server_name="swebench",
                    url=self.args.mcp_server,
                )
            else:
                mcp_script = Path(__file__).resolve().parent / "mcp_tools_swebench.py"
                await mcp_manager.connect_stdio(
                    server_name="swebench",
                    command=sys.executable,
                    args=[str(mcp_script)],
                )

            sandbox = Sandbox(sandbox_config, mcp_manager, task)
            # Build prompts
            system_prompt = PromptBuilder.build_swebench_system_prompt(
                sandbox.get_manual("swebench"))
            user_prompt = PromptBuilder.build_swebench_user_prompt(task)
            # Initialize orchestrator
            orchestrator = AgentOrchestrator(llm_client, sandbox, limits)
            solution_output = await orchestrator.run(
                task_id=str(task.instance_id),
                benchmark="swebench",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as e:
            # Build a minimal failure output so we always produce valid JSON
            task_id = str(task.instance_id) if task else "unknown"
            solution_output = SolutionOutput(
                task_id=task_id,
                benchmark="swebench",
                success=False,
                solution="",
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
                    output_path.write_text(solution_output.model_dump_json(indent=2))
            finally:
                if mcp_manager is not None:
                    try:
                        await mcp_manager.close()
                    except Exception:
                        pass
                if sandbox is not None:
                    try:
                        sandbox.close()
                    except Exception:
                        pass


def main():
    cli = SWEBenchCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
