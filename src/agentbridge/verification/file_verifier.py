from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.enums import FailureCategory, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.domain.verification import VerificationResult
from agentbridge.verification.base import Verifier


class FileExistsVerifier(Verifier):
    verifier_id = "fileexists"

    def check(
        self,
        item: AcceptanceItem,
        artifacts: list[Artifact],
        run_dir: Path,
        workspace: Path,
        permissions: Permissions,
    ) -> VerificationResult:
        del artifacts, run_dir, permissions
        assert item.path is not None
        target = (workspace / item.path).resolve()
        passed = target.exists()
        return VerificationResult(
            check_id=item.id,
            status=VerificationStatus.PASS if passed else VerificationStatus.FAIL,
            verifier_id=self.verifier_id,
            failure_category=None if passed else FailureCategory.ACCEPTANCE,
            detail=f"path={target}; exists={passed}",
        )
