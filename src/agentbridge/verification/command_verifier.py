import os
import shlex
import shutil

# Verifier commands are task-declared, bounded, and permission-gated.
import subprocess  # nosec B404
from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.enums import FailureCategory, PermissionMode, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.domain.verification import VerificationResult
from agentbridge.verification.base import Verifier

SHELL_MARKERS = ("|", "&&", "||", ">", "<", ";", "\n")


class CommandVerifier(Verifier):
    verifier_id = "command"

    def __init__(
        self,
        timeout_seconds: int = 300,
        evidence_dir: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.evidence_dir = evidence_dir

    def log_path(self, run_dir: Path, check_id: str) -> Path:
        directory = self.evidence_dir or run_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"verify-{check_id}.log"

    def check(
        self,
        item: AcceptanceItem,
        artifacts: list[Artifact],
        run_dir: Path,
        workspace: Path,
        permissions: Permissions,
    ) -> VerificationResult:
        del artifacts
        if item.command is None:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.INPUT,
                detail="Command acceptance is missing a command",
            )
        use_shell = any(marker in item.command for marker in SHELL_MARKERS)
        if use_shell and permissions.shell.mode != PermissionMode.ALLOW:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.PERMISSION,
                detail="Shell syntax was blocked by task permissions",
            )
        try:
            if use_shell:
                if os.name == "nt":
                    command = [
                        os.environ.get("COMSPEC", "cmd.exe"),
                        "/d",
                        "/s",
                        "/c",
                        item.command,
                    ]
                else:
                    command = [shutil.which("sh") or "/bin/sh", "-c", item.command]
            else:
                command = shlex.split(item.command, posix=os.name != "nt")
        except ValueError as exc:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.INPUT,
                detail=f"Invalid command syntax: {exc}",
            )
        try:
            # argv is explicit; any shell syntax has passed the permission gate above.
            result = subprocess.run(  # nosec B603
                command,
                shell=False,
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode(errors="replace")
                if isinstance(exc.stdout, bytes)
                else exc.stdout
            )
            stderr = (
                exc.stderr.decode(errors="replace")
                if isinstance(exc.stderr, bytes)
                else exc.stderr
            )
            log_path = self.log_path(run_dir, item.id)
            log_path.write_text((stdout or "") + (stderr or ""), encoding="utf-8")
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.ACCEPTANCE,
                detail=f"timeout_seconds={self.timeout_seconds}",
            )
        except OSError as exc:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.ENVIRONMENT,
                detail=str(exc),
            )
        log_path = self.log_path(run_dir, item.id)
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        passed = result.returncode == item.expected_exit_code
        return VerificationResult(
            check_id=item.id,
            status=VerificationStatus.PASS if passed else VerificationStatus.FAIL,
            verifier_id=self.verifier_id,
            failure_category=None if passed else FailureCategory.ACCEPTANCE,
            detail=f"exit_code={result.returncode}; expected={item.expected_exit_code}",
        )
