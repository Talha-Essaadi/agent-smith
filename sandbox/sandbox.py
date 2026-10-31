from schemas.sandbox import BaseSandbox, SandboxConfig, ExecutionResult
from sandbox.runner import DockerRunner


class Sandbox(BaseSandbox):
    def __init__(self, config: SandboxConfig) -> None:
        self.config = config
        self.runner = DockerRunner(config)

    def execute(self, code: str) -> ExecutionResult:
        # Delegate execution to DockerRunner
        return self.runner.run(code)

    def get_manual(self) -> str:
        # Return instructions available to the agent
        return "Python execution environment."

    def close(self) -> None:
        # Clean up Docker resources
        self.runner.close()