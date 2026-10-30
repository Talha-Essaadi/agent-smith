from typing import List, Optional
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Sandbox configuration for student solutions.
    Uses allowlist approach: only imports in authorized_imports are allowed.
    Everything else is blocked by default.
    """
    authorized_imports: List[str] = Field(
        default_factory=lambda: [
            "math", "math.*",
            "collections", "collections.*",
            "itertools", "re", "json",
            "typing", "typing.*",
            "functools", "operator",
            "heapq", "bisect", "copy",
            "string", "random",
            "datetime", "datetime.*",
            "array", "cmath",
        ]
    )
    allowed_directories: List[str] = Field(
        default_factory=lambda: [
            "/testbed", "/tmp/agent"
        ]
    )
    max_execution_time_seconds: int = 30
    max_memory_mb: int = 512 # Must be more than 6MB
    max_output_bytes: int = 100 * 1024  # 100 KB


class ExecutionResult(BaseModel):
    """Standardized response from Sandbox.execute(code)
     back to the Orchestrator."""
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    timed_out: bool = False
    truncated: bool = False
    is_final_answer: bool = False
    resource_limit_exceeded: bool = True
    final_answer_value: Optional[str] = None

    def to_observation_string(self) -> str:
        """Formats explicit feedback for the LLM (Spec Section V.1 Red Box)."""
        parts: List[str] = []
        if self.stdout:
            parts.append(f"[STDOUT]\n{self.stdout.rstrip()}")
        if self.stderr:
            parts.append(f"[STDERR]\n{self.stderr.rstrip()}")
        if self.error:
            parts.append(f"[EXECUTION ERROR]\n{self.error.rstrip()}")
        if self.timed_out:
            parts.append(
                "[WARNING: Execution hit the timeout limit. "
                "Output above may be partial. "
                "Optimize your code or avoid infinite loops.]"
            )
        if self.truncated:
            parts.append(
                "[WARNING: Tool/Sandbox output was"
                " truncated due to size limits. "
                "Use more specific queries or smaller line ranges.]"
            )
        if not parts and not self.is_final_answer:
            return "[Execution completed successfully with no output. "
            "Remember to use print() to inspect variables or tool results.]"
        return "\n\n".join(parts)


class BaseSandbox(ABC):
    """Abstract interface that Student 2's Sandbox
     and our MockSandbox must implement."""

    @abstractmethod
    def execute(self, code: str) -> ExecutionResult:
        """Executes Python code in the sandbox namespace
         and returns structured output."""
        pass

    @abstractmethod
    def get_manual(self) -> str:
        """Returns dynamically generated documentation
         for connected MCP tools + final_answer."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Cleans up any subprocesses,
         MCP connections, or Docker containers."""
        pass
