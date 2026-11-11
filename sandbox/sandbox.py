from schemas import BaseSandbox, SandboxConfig, ExecutionResult
from sandbox.mcp_manager import MCPManager
from sandbox.runner import DockerRunner
from textwrap import dedent

class Sandbox(BaseSandbox):
    def __init__(self, config: SandboxConfig, mcp_manager: MCPManager) -> None:
        self.config = config
        self.mcp_manager = mcp_manager
        self._runner = DockerRunner(config)
        # self.tool_registry = self._runner.tool_registry

    def execute(self, code: str) -> ExecutionResult:
        # Delegate execution to DockerRunner
        return self._runner.run(code)

    def get_manual(self, type: str) -> str:
        # Return instructions available to the agent

        if type not in ("mbpp", "swebench"):
            raise ValueError(
                f"Unknown benchmark type: {type}. "
                "Expected 'mbpp' or 'swebench'."
            )

        config = self.config

        # 1. Sandbox restrictions
        restrictions = dedent(f"""
            ## Sandbox Restrictions

            Authorized imports:
            {", ".join(config.authorized_imports)}

            Allowed directories:
            {", ".join(config.allowed_directories)}

            Execution limits:
            - Maximum execution time: {config.max_execution_time_seconds} seconds
            - Maximum memory: {config.max_memory_mb} MB
            - Maximum output: {config.max_output_bytes} bytes
            - Maximum disk usage: {config.max_disk_usage_mb} MB
            - Maximum CPU cores: {config.max_cpu_cores}
            - Maximum processes: {config.max_processes}

            Security:
            - Direct network access is disabled.
            - Filesystem access is restricted to authorized directories.
        """).strip()

        # 2. Benchmark-specific instructions
        if type == "mbpp":
            benchmark_manual = dedent("""
                ## MBPP Task

                You are solving a Python programming problem.

                - Implement the requested Python function.
                - Respect the required function signature.
                - Use the available tools to test your solution.
                - Verify your solution against the task requirements.
            """).strip()

        else:
            benchmark_manual = dedent("""
                ## SWE-bench Task

                You are solving a software engineering issue.

                - Inspect the repository before making changes.
                - Identify the relevant files and functions.
                - Implement the necessary modifications.
                - Use available tools to run relevant tests.
                - Avoid unrelated changes.
            """).strip()

        # 3. Available MCP tools for this benchmark
        tools_manual = "## Available MCP Tools\n"

        tools = [
            tool
            for tool in self.mcp_manager.list_tools()
            if tool.server_name == type
        ]

        if not tools:
            tools_manual += "\nNo MCP tools are registered for this benchmark."
        else:
            for tool in tools:
                tools_manual += (
                    f"\n### {tool.name}\n\n"
                    f"Description: {tool.description}\n\n"
                    f"Input schema:\n"
                    f"```json\n"
                    f"{json.dumps(tool.inputSchema, indent=2)}\n"
                    f"```\n\n"
                    f"Call this tool as a Python function named "
                    f"`{tool.name}`.\n"
                )

        # 4. Final answer instructions
        final_answer_manual = dedent("""
            ## Final Answer

            When you finish solving the task, call:

            final_answer("Your final answer")

            Calling final_answer() signals that the task is complete.
        """).strip()

        # 5. Combine all sections
        return "\n\n".join([
            f"# Agent Smith Sandbox Manual ({type.upper()})",
            benchmark_manual,
            restrictions,
            tools_manual,
            final_answer_manual,
        ])
    def close(self) -> None:
        # Clean up Docker resources
        self._runner.close()