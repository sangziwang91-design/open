from agentbridge.domain.enums import TaskState
from agentbridge.errors import InvalidTransitionError


ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.RECEIVED: {TaskState.VALIDATING},
    TaskState.VALIDATING: {TaskState.READY, TaskState.INVALID, TaskState.NEEDS_CLARIFICATION},
    TaskState.INVALID: {TaskState.CLOSED},
    TaskState.NEEDS_CLARIFICATION: {TaskState.READY, TaskState.INVALID, TaskState.CLOSED},
    TaskState.READY: {TaskState.BASELINING, TaskState.PAUSED, TaskState.SUPERSEDED},
    TaskState.BASELINING: {TaskState.DISPATCHING, TaskState.BLOCKED, TaskState.PAUSED},
    TaskState.BLOCKED: {TaskState.READY, TaskState.CLOSED, TaskState.PAUSED},
    TaskState.DISPATCHING: {TaskState.EXECUTING, TaskState.EXECUTOR_ERROR, TaskState.PAUSED},
    TaskState.EXECUTING: {
        TaskState.COLLECTING,
        TaskState.INTERRUPTED,
        TaskState.TIMED_OUT,
        TaskState.EXECUTOR_ERROR,
        TaskState.PAUSED,
    },
    TaskState.INTERRUPTED: {TaskState.RECOVERY_REQUIRED, TaskState.PAUSED},
    TaskState.TIMED_OUT: {TaskState.RECOVERY_REQUIRED, TaskState.PAUSED},
    TaskState.EXECUTOR_ERROR: {TaskState.RECOVERY_REQUIRED, TaskState.PAUSED},
    TaskState.COLLECTING: {TaskState.WAITING_VERIFICATION, TaskState.EXECUTOR_ERROR},
    TaskState.WAITING_VERIFICATION: {TaskState.VERIFYING, TaskState.PAUSED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.ACCEPTANCE_FAILED, TaskState.PAUSED},
    TaskState.ACCEPTANCE_FAILED: {TaskState.REPAIR_READY, TaskState.WAITING_HUMAN},
    TaskState.REPAIR_READY: {TaskState.DISPATCHING, TaskState.WAITING_HUMAN, TaskState.PAUSED},
    TaskState.WAITING_HUMAN: {TaskState.REJECTED, TaskState.REQUIRE_CHANGE, TaskState.REPAIR_READY},
    TaskState.REJECTED: {TaskState.CLOSED},
    TaskState.REQUIRE_CHANGE: {TaskState.REPAIR_READY, TaskState.CLOSED},
    TaskState.COMPLETED: {TaskState.LEARNING, TaskState.CLOSED},
    TaskState.LEARNING: {TaskState.CLOSED},
    TaskState.RECOVERY_REQUIRED: {TaskState.READY, TaskState.CLOSED, TaskState.PAUSED},
    TaskState.PAUSED: {TaskState.READY, TaskState.CLOSED},
    TaskState.SUPERSEDED: {TaskState.CLOSED},
    TaskState.ABORTED: {TaskState.CLOSED},
    TaskState.CLOSED: set(),
}


def allowed_targets(current: TaskState) -> set[TaskState]:
    return set(ALLOWED_TRANSITIONS.get(current, set()))


def validate_transition(current: TaskState, target: TaskState) -> bool:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(f"Invalid state transition: {current.value} -> {target.value}")
    return True
