from pathlib import Path

import pytest

from agentbridge.domain.enums import (
    ArtifactType,
    FailureCategory,
    VerificationStatus,
)
from agentbridge.domain.task import AcceptanceItem, Permissions
from agentbridge.interpreters.artifact_collector import (
    artifact_for,
    collect_execution_artifacts,
)
from agentbridge.verification.git_verifier import GitDiffVerifier


def test_artifact_path_must_stay_inside_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="outside run directory"):
        artifact_for("T", "R", outside, ArtifactType.LOG, "test", run_dir)


def test_git_diff_verifier_rejects_tampered_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    diff_path = run_dir / "git.diff"
    diff_path.write_text("original", encoding="utf-8")
    artifact = artifact_for("T", "R", diff_path, ArtifactType.DIFF, "test", run_dir)
    diff_path.write_text("tampered", encoding="utf-8")
    result = GitDiffVerifier().check(
        AcceptanceItem(id="A1", type="gitdiff"),
        [artifact],
        run_dir,
        tmp_path,
        Permissions(),
    )
    assert result.status == VerificationStatus.UNKNOWN
    assert result.failure_category == FailureCategory.TOOL
    assert "sha256_mismatch" in result.detail


def test_collector_rejects_executor_workspace_switch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    command = run_dir / "command.txt"
    stdout = run_dir / "stdout.log"
    stderr = run_dir / "stderr.log"
    for path in (command, stdout, stderr):
        path.write_text("", encoding="utf-8")
    raw = {
        "command_path": str(command),
        "stdout_path": str(stdout),
        "stderr_path": str(stderr),
        "workspace": str(tmp_path / "other"),
    }
    with pytest.raises(ValueError, match="different workspace"):
        collect_execution_artifacts("T", "R", raw, run_dir, tmp_path)
