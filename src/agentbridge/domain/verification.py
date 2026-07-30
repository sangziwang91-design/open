from pydantic import BaseModel, Field

from .enums import ClaimLevel, FailureCategory, VerificationStatus


class VerificationResult(BaseModel):
    check_id: str
    status: VerificationStatus
    verifier_id: str
    verifier_version: str = "1.0"
    failure_category: FailureCategory | None = None
    artifact_id: str | None = None
    detail: str = ""


class ClaimReport(BaseModel):
    allowed_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    max_claim_level: ClaimLevel = ClaimLevel.GENERATED
    completion_scope: str = "acceptance_only"
