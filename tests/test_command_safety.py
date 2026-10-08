import shlex
import sys
import time
from pathlib import Path

from agentbridge.domain.enums import FailureCategory, PermissionMode, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.verification.command_verifier import (
    CommandVerifier,
    split_verification_argv,
)


def run(command: str, workspace: Path, *, shell: PermissionMode = PermissionMode.ALLOW):
    permissions = Permissions()
    permissions.shell.mode = shell
    item = AcceptanceItem(id="A1", type="command", command=command)
    return CommandVerifier(timeout_seconds=1).check(
        item, [], workspace, workspace, permissions
    )


def test_shell_pipeline_is_explicitly_permission_gated(tmp_path: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -c \"print('ok')\" | grep ok"
    assert run(command, tmp_path).status == VerificationStatus.PASS
    denied = run(command, tmp_path, shell=PermissionMode.DENY)
    assert denied.status == VerificationStatus.FAIL
    assert denied.failure_category == FailureCategory.PERMISSION


def test_command_timeout_is_bounded_and_recorded(tmp_path: Path) -> None:
    command = f'{shlex.quote(sys.executable)} -c "import time; time.sleep(5)"'
    started = time.monotonic()
    result = run(command, tmp_path)
    elapsed = time.monotonic() - started
    assert elapsed < 3
    assert result.status == VerificationStatus.FAIL
    assert result.failure_category == FailureCategory.ACCEPTANCE
    assert "timeout_seconds=1" in result.detail
    assert (tmp_path / "verify-A1.log").exists()


def test_invalid_command_quoting_is_input_failure(tmp_path: Path) -> None:
    result = run("'unterminated", tmp_path)
    assert result.status == VerificationStatus.FAIL
    assert result.failure_category == FailureCategory.INPUT


def test_windows_quoted_hidden_test_path_is_not_passed_with_literal_quotes() -> None:
    command = 'python -m pytest -q "C:\\Users\\runner admin\\frozen-tests\\test_logic.py"'
    assert split_verification_argv(command, windows=True) == [
        "python", "-m", "pytest", "-q",
        "C:\\Users\\runner admin\\frozen-tests\\test_logic.py",
    ]
    assert split_verification_argv('python -m pytest -q tests/test_logic.py', windows=True) == [
        "python", "-m", "pytest", "-q", "tests/test_logic.py",
    ]


def test_posix_quoted_hidden_test_path_is_preserved_without_quote_chars() -> None:
    assert split_verification_argv('python -m pytest -q "/tmp/frozen tests/test.py"', windows=False) == [
        "python", "-m", "pytest", "-q", "/tmp/frozen tests/test.py",
    ]
