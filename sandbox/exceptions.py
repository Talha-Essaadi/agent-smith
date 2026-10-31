"""Custom exceptions for sandbox execution."""


class SandboxError(Exception):
    """Base exception for all sandbox-related errors."""


class SandboxConfigurationError(SandboxError):
    """Raised when the sandbox configuration is invalid."""




class SandboxExecutionError(SandboxError):
    """Raised when code execution fails unexpectedly."""


class SandboxTimeoutError(SandboxExecutionError):
    """Raised when code execution exceeds the allowed time limit."""


class SandboxResourceLimitError(SandboxExecutionError):
    """Raised when execution exceeds a resource limit, such as memory."""




class SandboxImportError(SandboxError):
    """Raised when code imports a module that is not authorized."""


class SandboxCleanupError(SandboxError):
    """Raised when sandbox resources cannot be cleaned up properly."""