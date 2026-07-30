from typing import Literal

from pydantic import BaseModel, Field

from .enums import FailureCategory


class FeedbackEnvelope(BaseModel):
    task_id: str
    run_id: str
    attempt_id: str | None = None
    status: Literal["COMPLETED", "PARTIAL", "FAILED", "BLOCKED"]
    evidence_summary: list[str] = Field(default_factory=list)
    failure_category: FailureCategory | None = None
    allowed_next_action: Literal["REPAIR", "INPUT", "ABORT", "CLOSE"]
    forbidden_actions: list[str] = Field(default_factory=list)
    new_constraints: list[str] = Field(default_factory=list)
    requires_human_decision: bool = False
    question_to_human: str | None = None
