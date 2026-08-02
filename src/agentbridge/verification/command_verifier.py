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

SHELL_MARKERS = frozenset("|&><;\n")


def contains_shell_syntax(command: str) -> bool:
    """Return true only for shell operators outside quoted arguments.

    Acceptance commands often contain Python or JavaScript snippets such as
    ``python -c "a=1; print(a)"``. Treating the semicolon inside that quoted
    argument as a shell operator incorrectly routes an otherwise direct argv
    through cmd.exe on Windows and changes its quoting semantics.
    """
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            continue
        if character in SHELL_MARKERS:
            return True
    return False


def split_direct_command(command: str, windows: bool | None = None) -> list[str]:
    is_windows = os.name == "nt" if windows is None else windows
    tokens = shlex.split(command, posix=not is_windows)
    if not is_windows:
        return tokens
    # shlex(posix=False) preserves Windows backslashes but also preserves paired
    # quote characters. subprocess.list2cmdline expects the quote-free argv.
    return [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]


class CommandVerifier(Verifier):
    verifier_id = "command"

    def __init__(
        self,
        timeout_seconds: int = 300,
        evidence_dir: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.evidence_dir = evidence_dir
        self.environment = dict(environment) if environment is not None else None

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
        use_shell = contains_shell_syntax(item.command)
        if permissions.shell.mode != PermissionMode.ALLOW:
            return VerificationResult(
                check_id=item.id,
                status=VerificationStatus.FAIL,
                verifier_id=self.verifier_id,
                failure_category=FailureCategory.PERMISSION,
                detail=(
                    "Command execution was blocked by task shell permissions"
                    if not use_shell
                    else "Shell syntax was blocked by task permissions"
                ),
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
                command = split_direct_command(item.command)
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
                env=self.environment,
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
