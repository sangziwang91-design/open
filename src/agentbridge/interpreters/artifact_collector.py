import hashlib
import subprocess
from pathlib import Path

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.enums import ArtifactType


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_for(
    task_id: str,
    run_id: str,
    path: Path,
    artifact_type: ArtifactType,
    created_by: str,
) -> Artifact:
    return Artifact(
        task_id=task_id,
        run_id=run_id,
        type=artifact_type,
        path=str(path.resolve()),
        sha256=hash_file(path),
        created_by=created_by,
    )


def _run_git(workspace: Path, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def capture_baseline(task_id: str, run_id: str, workspace: str, run_dir: Path) -> list[Artifact]:
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).resolve()
    baseline_path = run_dir / "baseline.txt"
    lines = [f"workspace={workspace_path}"]
    if workspace_path.exists():
        lines.append("entries=" + ",".join(sorted(p.name for p in workspace_path.iterdir())))
    else:
        lines.append("workspace_missing=true")
    code, stdout, stderr = _run_git(workspace_path, ["status", "--short"])
    lines.append(f"git_status_exit={code}")
    lines.append(stdout)
    if stderr:
        lines.append(stderr)
    baseline_path.write_text("\n".join(lines), encoding="utf-8")
    return [artifact_for(task_id, run_id, baseline_path, ArtifactType.BASELINE, "baseline")]


def collect_execution_artifacts(
    task_id: str, run_id: str, raw_output: dict, run_dir: Path
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    mapping = {
        "command_path": ArtifactType.COMMAND,
        "stdout_path": ArtifactType.STDOUT,
        "stderr_path": ArtifactType.STDERR,
    }
    for key, artifact_type in mapping.items():
        path_value = raw_output.get(key)
        if path_value and Path(path_value).exists():
            artifacts.append(
                artifact_for(task_id, run_id, Path(path_value), artifact_type, "executor")
            )

    workspace = Path(raw_output.get("workspace", ".")).resolve()
    diff_path = run_dir / "git.diff"
    code, stdout, stderr = _run_git(workspace, ["diff", "--binary", "--no-ext-diff"])
    if code == 0:
        diff_path.write_text(stdout, encoding="utf-8")
    else:
        diff_path.write_text(f"git diff unavailable\n{stderr}", encoding="utf-8")
    artifacts.append(artifact_for(task_id, run_id, diff_path, ArtifactType.DIFF, "collector"))
    return artifacts
