from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import TaskState


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskRuntime(BaseModel):
    task_id: str
    task_version: int = 1
    run_id: str = Field(default_factory=lambda: f"RUN-{uuid4().hex[:8].upper()}")
    state: TaskState = TaskState.RECEIVED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    latest_event_id: str | None = None
    executor_id: str | None = None
    workspace: str | None = None
    attempt_count: int = 0
    revision: int = Field(default=0, ge=0)
