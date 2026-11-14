import socket
import io
import signal
import resource
from contextlib import redirect_stdout, redirect_stderr
from typing import Optional, Any, Dict
from schemas import BaseSandbox, SandboxConfig, ExecutionResult
from .security import SandboxSecurity


class _FinalAnswerSignal(BaseException):
    pass


class Sandbox(BaseSandbox):
    def __init__(self,
                 config: Optional[SandboxConfig] = None,
                 mcp_client: Optional[Any] = None) -> None:

        self.config = config or SandboxConfig()
        self.security = SandboxSecurity(self.config)
        self.mcp_client = mcp_client

        self._is_final_answer = False
        self._final_answer: Optional[str] = None

        self.namespace: Dict[str, Any] = {}
        self._setup_namespace()

    def _setup_namespace(self):
        self.namespace["__builtins__"] = self.security.build_safe_builtins()
        self.namespace["final_answer"] = self._final_answer_func
        if self.mcp_client:
            self._set_mcp_tools()

    def _set_mcp_tools(self):
        pass

    def _final_answer_func(self, answer: Any) -> None:
        """Helper function called in code to signal final answer submission."""
        self._is_final_answer = True
        self._final_answer = str(answer) if answer is not None else ""
        raise _FinalAnswerSignal

    @staticmethod
    def _blocked_socket(*args, **kwargs) -> None:
        raise PermissionError("Network access is disabled inside the sandbox")

    @staticmethod
    def _timeout_handler(signum, frame):
        raise TimeoutError("Sandbox execution timed out")

    def execute(self, code: str):
        self._setup_namespace()
        self._is_final_answer = False
        self._final_answer = None
        error_msg: Optional[str] = None
        timed_out = False
        truncated = False

        stdout = io.StringIO()
        stderr = io.StringIO()
        org_socket_func = socket.socket
        old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)
        old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)

        try:
            self.security.validate_ast(code)

            socket.socket = self._blocked_socket
            signal.setitimer(signal.ITIMER_REAL,
                             self.config.max_execution_time_seconds)
            resource.setrlimit(resource.RLIMIT_AS,
                               (self.config.max_memory_mb * 1024 * 1024,
                                old_hard))

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exec(code, self.namespace)

        except (SyntaxError, PermissionError) as e:
            error_msg = f"{type(e).__name__}: {e}"
        except TimeoutError as e:
            timed_out = True
            error_msg = f"TimeoutError: {e}"
        except MemoryError as e:
            error_msg = "MemoryError: Code exceeded maximum allowed RAM limit"
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"  
        except _FinalAnswerSignal:
            pass
        finally:
            socket.socket = org_socket_func
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            resource.setrlimit(resource.RLIMIT_AS, (old_soft, old_hard))

        stderr = stderr.getvalue()
        stdout = stdout.getvalue()
        if len(stdout) > 50_000 or len(stderr) > 50_000:
            stderr = stderr[:50_000]
            stdout = stdout[:50_000]
            truncated = True

        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            error=error_msg,
            timed_out=timed_out,
            truncated=truncated,
            is_final_answer=self._is_final_answer,
            final_answer_value=self._final_answer
        )

    def get_manual(self) -> str:
        return ""

    def close(self) -> None:
        pass
