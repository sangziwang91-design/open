class AgentBridgeError(Exception):
    """Base package error."""


class InvalidTransitionError(AgentBridgeError):
    """Raised when a state transition is not allowed."""


class ExecutorUnavailableError(AgentBridgeError):
    """Raised when an executor binary is unavailable."""


class TaskNotFoundError(AgentBridgeError):
    """Raised when a task or run cannot be found."""
