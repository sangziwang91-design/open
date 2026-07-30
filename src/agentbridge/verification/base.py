from abc import ABC, abstractmethod
from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.domain.verification import VerificationResult


class Verifier(ABC):
    verifier_id: str
    verifier_version = "1.0"

    @abstractmethod
    def check(
        self,
        item: AcceptanceItem,
        artifacts: list[Artifact],
        run_dir: Path,
        workspace: Path,
        permissions: Permissions,
    ) -> VerificationResult: ...
