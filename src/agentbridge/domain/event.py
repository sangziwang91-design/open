from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str = Field(default_factory=lambda: f"EVT-{uuid4().hex[:12].upper()}")
    task_id: str
    run_id: str
    sequence_id: int | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    event_type: str
    payload: dict[str, Any]
