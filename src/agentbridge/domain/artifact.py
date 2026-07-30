from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import ArtifactType


def utc_now() -> datetime:
    return datetime.now(UTC)


class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"ART-{uuid4().hex[:8].upper()}")
    task_id: str
    run_id: str
    type: ArtifactType
    path: str
    sha256: str
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
