from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .enums import ExecutorCapability, PermissionMode


def utc_now() -> datetime:
    return datetime.now(UTC)


class Source(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    adapter: str
    conversation_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices("conversation_ref", "conversationref"),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        validation_alias=AliasChoices("created_at", "createdat"),
    )


class Target(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    executor_id: Literal["fake", "opencode"] = Field(
        default="opencode", validation_alias=AliasChoices("executor_id", "executorid")
    )
    capabilities_required: list[ExecutorCapability] = Field(
        default_factory=lambda: [
            ExecutorCapability.FILESYSTEM,
            ExecutorCapability.SHELL,
        ],
        validation_alias=AliasChoices("capabilities_required", "capabilitiesrequired"),
    )
    workspace: str
    branch: str | None = None


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class AcceptanceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    type: Literal["command", "gitdiff", "fileexists"]
    command: str | None = None
    expected_exit_code: int = Field(
        default=0,
        validation_alias=AliasChoices("expected_exit_code", "expectedexitcode"),
    )
    rule: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "AcceptanceItem":
        if self.type == "command" and not self.command:
            raise ValueError("command acceptance requires command")
        if self.type == "fileexists" and not self.path:
            raise ValueError("fileexists acceptance requires path")
        if self.type == "gitdiff" and self.rule not in {None, "non_empty", "empty"}:
            raise ValueError("gitdiff rule must be 'non_empty' or 'empty'")
        return self


class PermissionRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    mode: PermissionMode = PermissionMode.DENY
    inherited_from: str | None = Field(
        default=None, validation_alias=AliasChoices("inherited_from", "inheritedfrom")
    )


class Permissions(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    file_write: PermissionRule = Field(
        default_factory=lambda: PermissionRule(mode=PermissionMode.ALLOW),
        validation_alias=AliasChoices("file_write", "filewrite"),
    )
    delete: PermissionRule = Field(
        default_factory=lambda: PermissionRule(mode=PermissionMode.ASK)
    )
    network: PermissionRule = Field(default_factory=PermissionRule)
    shell: PermissionRule = Field(
        default_factory=lambda: PermissionRule(mode=PermissionMode.ALLOW)
    )

    def effective(self, category: str) -> PermissionMode:
        return getattr(self, category).mode


class Budget(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    max_executor_rounds: int = Field(
        default=3,
        ge=1,
        validation_alias=AliasChoices("max_executor_rounds", "maxexecutorrounds"),
    )
    max_retries_per_node: int = Field(
        default=2,
        ge=0,
        validation_alias=AliasChoices("max_retries_per_node", "maxretriespernode"),
    )
    timeout_seconds: int = Field(
        default=1800,
        ge=1,
        validation_alias=AliasChoices("timeout_seconds", "timeoutseconds"),
    )


class StopConditions(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    success: str
    blocked: str
    no_progress: str = Field(
        default="two consecutive rounds without new evidence",
        validation_alias=AliasChoices("no_progress", "noprogress"),
    )
    budget_exhausted: bool = Field(
        default=True,
        validation_alias=AliasChoices("budget_exhausted", "budgetexhausted"),
    )


class ContextRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["skill", "memoryquery", "file", "url"]
    ref: str | None = None
    query: str | None = None


class TaskEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_version: str = Field(
        default="1.0", validation_alias=AliasChoices("schema_version", "schemaversion")
    )
    task_id: str = Field(
        default_factory=lambda: f"TASK-{uuid4().hex[:8].upper()}",
        validation_alias=AliasChoices("task_id", "taskid"),
    )
    title: str
    type: str
    goal: str
    source: Source
    target: Target
    scope: Scope = Field(default_factory=Scope)
    constraints: list[str] = Field(default_factory=list)
    acceptance: Annotated[list[AcceptanceItem], Field(min_length=1)]
    permissions: Permissions = Field(default_factory=Permissions)
    budget: Budget = Field(default_factory=Budget)
    stop: StopConditions
    context_refs: list[ContextRef] = Field(
        default_factory=list,
        validation_alias=AliasChoices("context_refs", "contextrefs"),
    )

    @model_validator(mode="after")
    def validate_acceptance_ids(self) -> "TaskEnvelope":
        ids = [item.id for item in self.acceptance]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance ids must be unique")
        return self
