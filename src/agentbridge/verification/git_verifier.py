from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.enums import ArtifactType, FailureCategory, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.domain.verification import VerificationResult
from agentbridge.interpreters.artifact_collector import validate_artifact_file
from agentbridge.verification.base import Verifier


class GitDiffVerifier(Verifier):
    verifier_id = "gitdiff"

    def check(
        self,
        item: AcceptanceItem,
        artifacts: list[Artifact],
        run_dir: Path,
        workspace: Path,
        permissions: Permissions,
    ) -> VerificationResult:
        del workspace, permissions
        diff = next(
            (a for a in reversed(artifacts) if a.type == ArtifactType.DIFF), None
        )
        if diff is None:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.UNKNOWN,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.ENVIRONMENT,
                detail="No git diff artifact was collected",
            )
        path, integrity_error = validate_artifact_file(diff, run_dir)
        if integrity_error is not None or path is None:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.UNKNOWN,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.TOOL,
                artifact_id=diff.artifact_id,
                detail=f"Evidence integrity failed: {integrity_error}",
            )
        content = path.read_text(encoding="utf-8")
        if content.startswith("git diff unavailable"):
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.UNKNOWN,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.ENVIRONMENT,
                artifact_id=diff.artifact_id,
                detail="Workspace is not a readable git repository",
            )
        rule = item.rule or "non_empty"
        passed = (
            bool(content.strip()) if rule == "non_empty" else not bool(content.strip())
        )
        return VerificationResult(
            check_id=item.id,
            status=VerificationStatus.PASS if passed else VerificationStatus.FAIL,
            verifier_id=self.verifier_id,
            failure_category=None if passed else FailureCategory.ACCEPTANCE,
            artifact_id=diff.artifact_id,
            detail=f"rule={rule}; bytes={len(content.encode())}",
        )
