from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class CapabilitySnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: f"SNP-{uuid4().hex[:8].upper()}")
    environment: dict[str, str]
    detected_at: datetime = Field(default_factory=utc_now)
