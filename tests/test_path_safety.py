from pathlib import Path

import pytest

from agentbridge.domain.enums import FailureCategory, VerificationStatus
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.verification.file_verifier import FileExistsVerifier


def check(path: str, workspace: Path):
    item = AcceptanceItem(id="A1", type="fileexists", path=path)
    return FileExistsVerifier().check(item, [], workspace, workspace, Permissions())


def test_file_verifier_accepts_file_inside_workspace(tmp_path: Path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("ok", encoding="utf-8")
    result = check("result.txt", tmp_path)
    assert result.status == VerificationStatus.PASS


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd"])
def test_file_verifier_rejects_path_outside_workspace(
    tmp_path: Path, path: str
) -> None:
    (tmp_path.parent / "outside.txt").write_text("secret", encoding="utf-8")
    result = check(path, tmp_path)
    assert result.status == VerificationStatus.FAIL
    assert result.failure_category == FailureCategory.PERMISSION


def test_file_verifier_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    result = check("link.txt", tmp_path)
    assert result.status == VerificationStatus.FAIL
    assert result.failure_category == FailureCategory.PERMISSION
