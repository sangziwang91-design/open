import os
import shlex
import sys
import time
from pathlib import Path

from agentbridge.domain.enums import FailureCategory, PermissionMode, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.verification.command_verifier import (
    CommandVerifier,
    contains_shell_syntax,
    split_direct_command,
)


def run(command: str, workspace: Path, *, shell: PermissionMode = PermissionMode.ALLOW):
    permissions = Permissions()
    permissions.shell.mode = shell
    item = AcceptanceItem(id="A1", type="command", command=command)
    return CommandVerifier(timeout_seconds=1).check(
        item, [], workspace, workspace, permissions
    )


def test_shell_pipeline_is_explicitly_permission_gated(tmp_path: Path) -> None:
    if os.name == "nt":
        command = "echo ok | findstr ok"
    else:
        command = f"{shlex.quote(sys.executable)} -c \"print('ok')\" | grep ok"
    assert run(command, tmp_path).status == VerificationStatus.PASS
    denied = run(command, tmp_path, shell=PermissionMode.DENY)
    assert denied.status == VerificationStatus.FAIL
    assert denied.failure_category == FailureCategory.PERMISSION


def test_direct_process_is_also_permission_gated(tmp_path: Path) -> None:
    command = f"{shlex.quote(sys.executable)} --version"
    denied = run(command, tmp_path, shell=PermissionMode.DENY)
    assert denied.status == VerificationStatus.FAIL
    assert denied.failure_category == FailureCategory.PERMISSION
    assert "Command execution was blocked" in denied.detail


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


def test_windows_direct_command_split_removes_quotes_without_losing_backslashes() -> (
    None
):
    assert split_direct_command(
        'python -c "raise SystemExit(9)" "C:\\Program Files\\demo"',
        windows=True,
    ) == ["python", "-c", "raise SystemExit(9)", "C:\\Program Files\\demo"]


def test_shell_detection_ignores_operators_inside_quoted_arguments() -> None:
    assert not contains_shell_syntax('python -c "a=1; print(a | 2)"')
    assert contains_shell_syntax('python -c "print(1)" | findstr 1')
    assert contains_shell_syntax("python -m pytest && echo complete")


def test_command_verifier_can_run_with_filtered_environment(tmp_path: Path) -> None:
    permissions = Permissions()
    item = AcceptanceItem(
        id="A1",
        type="command",
        command=(
            f'{shlex.quote(sys.executable)} -c "import os; '
            "raise SystemExit(0 if os.getenv('BLOCKED_SECRET') is None else 9)\""
        ),
    )
    result = CommandVerifier(
        timeout_seconds=2,
        environment={"PATH": str(Path(sys.executable).parent)},
    ).check(item, [], tmp_path, tmp_path, permissions)
    assert result.status == VerificationStatus.PASS
