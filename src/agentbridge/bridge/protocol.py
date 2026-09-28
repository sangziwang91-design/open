import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from agentbridge.domain.enums import ClaimLevel
from agentbridge.domain.task import AcceptanceItem

BridgeIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]


class BrainTaskMessage(BaseModel):
    """The only task shape accepted from an armed browser conversation.

    It intentionally has no workspace, executable, permission, or environment
    fields. Those authority-bearing settings stay on the local controller.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: Literal["agentbridge/1"] = "agentbridge/1"
    message_type: Literal["task"] = "task"
    session_id: BridgeIdentifier
    request_id: BridgeIdentifier
    parent_request_id: BridgeIdentifier | None = None
    title: str = Field(default="Chat task", min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=20_000)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    acceptance: Annotated[list[AcceptanceItem], Field(min_length=1, max_length=20)]
    timeout_seconds: int = Field(default=1800, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_constraints(self) -> "BrainTaskMessage":
        if any(not value.strip() or len(value) > 2_000 for value in self.constraints):
            raise ValueError(
                "constraints must be non-empty and at most 2000 characters"
            )
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class BridgeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    detail: str


class BridgeArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    sha256: str


class BridgeResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["agentbridge/1"] = "agentbridge/1"
    message_type: Literal["result"] = "result"
    session_id: str
    request_id: str
    job_id: str
    task_id: str | None = None
    run_id: str | None = None
    status: Literal["COMPLETED", "PARTIAL", "FAILED", "BLOCKED"]
    state: str
    summary: str
    checks: list[BridgeCheck] = Field(default_factory=list)
    artifacts: list[BridgeArtifact] = Field(default_factory=list)
    executor_excerpt: str | None = None
    claim_level: ClaimLevel = ClaimLevel.GENERATED
    next_action: Literal["REPAIR", "INPUT", "ABORT", "CLOSE"]
    requires_human_decision: bool = False
    question_to_human: str | None = None
    error: str | None = None


class BridgeJobView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    request_id: str
    status: Literal["QUEUED", "RUNNING", "FINISHED", "ERROR"]
    task_id: str | None = None
    run_id: str | None = None
    result: BridgeResultMessage | None = None
    error: str | None = None
    created_at: str
    updated_at: str
