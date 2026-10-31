import argparse
from pathlib import Path

from agent.config import AgentConfig
from agent import PromptBuilder, AgentOrchestrator, LLMClient
from sandbox.fake_sandbox import MockSandbox
from schemas import MBPPTaskInput, SolutionOutput


class MBPPCLI:
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
            required=False, help="Name of the model to use",
            default="qwen/qwen3-235b-a22b-2507"
        )
        self.parser.add_argument(
            "--provider-url", type=str,
            required=False, help="Base URL of the provider",
            default="https://openrouter.ai/api/v1"
        )
        self.parser.add_argument(
            "--env-file", type=str,
            required=False, help="Path to the .env file"
        )
        self.parser.add_argument(
            "--max-iterations", type=int, required=False,
            default=None, help="Maximum number of iterations"
        )
        self.args = self.parser.parse_args()

    def _load_task(self) -> MBPPTaskInput:
        task_file = self.args.task_file
        with open(task_file, "r") as f:
            task = f.read()
        task = MBPPTaskInput.model_validate_json(task)
        return task

    def run(self):
        task = None
        sandbox = None
        try:
            # Load task
            task = self._load_task()
            # Get limits
            limits = AgentConfig().get_limits("mbpp", self.args.max_iterations)
            # Initialize sandbox
            sandbox = MockSandbox()
            # Build prompts
            system_prompt = PromptBuilder.build_mbpp_system_prompt(
                sandbox.get_manual())
            user_prompt = PromptBuilder.build_mbpp_user_prompt(task)
            # Initialize llm client
            llm_client = LLMClient(model_name=self.args.model_name,
                                   provider_url=self.args.provider_url,
                                   env_file=self.args.env_file)
            # Initialize orchestrator
            orchestrator = AgentOrchestrator(llm_client, sandbox, limits)
            solution_output = orchestrator.run(task_id=str(task.task_id),
                                               benchmark="mbpp",
                                               system_prompt=system_prompt,
                                               user_prompt=user_prompt)
        except Exception as e:
            # Build a minimal failure output so we always produce valid JSON
            task_id = str(task.task_id) if task else "unknown"
            solution_output = SolutionOutput(
                task_id=task_id,
                benchmark="mbpp",
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
            # Always write output
            Path(self.args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(self.args.output, "w") as f:
                f.write(solution_output.model_dump_json(indent=2))
            if sandbox is not None:
                sandbox.close()


def main():
    cli = MBPPCLI()
    cli.run()


if __name__ == "__main__":
    main()
