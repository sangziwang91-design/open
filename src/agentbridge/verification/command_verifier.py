import os
import shlex
import subprocess
from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.enums import FailureCategory, PermissionMode, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.domain.verification import VerificationResult
from agentbridge.verification.base import Verifier


SHELL_MARKERS = ("|", "&&", "||", ">", "<", ";")


class CommandVerifier(Verifier):
    verifier_id = "command"

    def check(
        self,
        item: AcceptanceItem,
        artifacts: list[Artifact],
        run_dir: Path,
        workspace: Path,
        permissions: Permissions,
    ) -> VerificationResult:
        del artifacts
        assert item.command is not None
        use_shell = any(marker in item.command for marker in SHELL_MARKERS)
        if use_shell and permissions.shell.mode != PermissionMode.ALLOW:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.PERMISSION,
                detail="Shell syntax was blocked by task permissions",
            )
        command = item.command if use_shell else shlex.split(item.command, posix=os.name != "nt")
        try:
            result = subprocess.run(
                command,
                shell=use_shell,
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.ENVIRONMENT,
                detail=str(exc),
            )
        log_path = run_dir / f"verify-{item.id}.log"
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        passed = result.returncode == item.expected_exit_code
        return VerificationResult(
            check_id=item.id,
            status=VerificationStatus.PASS if passed else VerificationStatus.FAIL,
            verifier_id=self.verifier_id,
            failure_category=None if passed else FailureCategory.ACCEPTANCE,
            detail=f"exit_code={result.returncode}; expected={item.expected_exit_code}",
        )
