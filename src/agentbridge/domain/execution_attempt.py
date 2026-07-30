from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import AttemptStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionAttempt(BaseModel):
    attempt_id: str = Field(default_factory=lambda: f"ATT-{uuid4().hex[:8].upper()}")
    run_id: str
    task_id: str
    executor_id: str
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: AttemptStatus = AttemptStatus.CREATED
    exit_code: int | None = None
    signal: str | None = None
