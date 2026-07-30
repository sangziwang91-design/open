from datetime import datetime, timezone

from agentbridge.control.transitions import validate_transition
from agentbridge.domain.enums import TaskState
from agentbridge.domain.event import AgentEvent
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.persistence.repository import AgentRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StateManager:
    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def transition(
        self,
        runtime: TaskRuntime,
        target: TaskState,
        event_type: str,
        reason: str,
        actor: str = "system",
        extra: dict | None = None,
    ) -> AgentEvent:
        validate_transition(runtime.state, target)
        payload = {
            "actor": actor,
            "reason": reason,
            "from_state": runtime.state.value,
            "to_state": target.value,
            **(extra or {}),
        }
        event = self.repository.append_event(
            AgentEvent(
                task_id=runtime.task_id,
                run_id=runtime.run_id,
                event_type=event_type,
                payload=payload,
            )
        )
        runtime.state = target
        runtime.updated_at = utc_now()
        runtime.latest_event_id = event.event_id
        self.repository.update_runtime(runtime)
        return event

    def force_recovery(
        self, runtime: TaskRuntime, reason: str, actor: str = "system"
    ) -> AgentEvent:
        if runtime.state in {TaskState.CLOSED, TaskState.COMPLETED, TaskState.ABORTED}:
            raise ValueError(f"Cannot force recovery from terminal state {runtime.state.value}")
        event = self.repository.append_event(
            AgentEvent(
                task_id=runtime.task_id,
                run_id=runtime.run_id,
                event_type="ForcedRecovery",
                payload={
                    "actor": actor,
                    "reason": reason,
                    "from_state": runtime.state.value,
                    "to_state": TaskState.RECOVERY_REQUIRED.value,
                    "forced": True,
                },
            )
        )
        runtime.state = TaskState.RECOVERY_REQUIRED
        runtime.updated_at = utc_now()
        runtime.latest_event_id = event.event_id
        self.repository.update_runtime(runtime)
        return event
