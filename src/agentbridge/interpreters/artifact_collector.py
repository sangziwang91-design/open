import hashlib
import shutil

# Subprocess use is limited to fixed git evidence commands.
import subprocess  # nosec B404
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
    root: Path,
) -> Artifact:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"Artifact path is outside run directory: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"Artifact is not a readable file: {resolved_path}")
    return Artifact(
        task_id=task_id,
        run_id=run_id,
        type=artifact_type,
        path=str(resolved_path),
        sha256=hash_file(resolved_path),
        created_by=created_by,
    )


def validate_artifact_file(
    artifact: Artifact, root: Path
) -> tuple[Path | None, str | None]:
    path = Path(artifact.path).resolve()
    if not path.is_relative_to(root.resolve()):
        return None, "artifact_path_outside_run_directory"
    if not path.is_file():
        return None, "artifact_file_missing"
    if hash_file(path) != artifact.sha256:
        return None, "artifact_sha256_mismatch"
    return path, None


def _run_git(workspace: Path, args: list[str]) -> tuple[int, str, str]:
    git = shutil.which("git")
    if git is None:
        return 127, "", "git executable was not found on PATH"
    # The git path is resolved and every caller supplies internal fixed arguments.
    result = subprocess.run(  # nosec B603
        [git, "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def capture_baseline(
    task_id: str, run_id: str, workspace: str, run_dir: Path
) -> list[Artifact]:
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).resolve()
    baseline_path = run_dir / "baseline.txt"
    lines = [f"workspace={workspace_path}"]
    if workspace_path.exists():
        lines.append(
            "entries=" + ",".join(sorted(p.name for p in workspace_path.iterdir()))
        )
    else:
        lines.append("workspace_missing=true")
    code, stdout, stderr = _run_git(workspace_path, ["status", "--short"])
    lines.append(f"git_status_exit={code}")
    lines.append(stdout)
    if stderr:
        lines.append(stderr)
    baseline_path.write_text("\n".join(lines), encoding="utf-8")
    return [
        artifact_for(
            task_id,
            run_id,
            baseline_path,
            ArtifactType.BASELINE,
            "baseline",
            run_dir,
        )
    ]


def collect_execution_artifacts(
    task_id: str,
    run_id: str,
    raw_output: dict,
    run_dir: Path,
    expected_workspace: str | Path,
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
                artifact_for(
                    task_id,
                    run_id,
                    Path(path_value),
                    artifact_type,
                    "executor",
                    run_dir,
                )
            )

    workspace = Path(raw_output.get("workspace", ".")).resolve()
    if workspace != Path(expected_workspace).resolve():
        raise ValueError("Executor reported a different workspace")
    diff_path = run_dir / "git.diff"
    code, stdout, stderr = _run_git(workspace, ["diff", "--binary", "--no-ext-diff"])
    if code == 0:
        diff_path.write_text(stdout, encoding="utf-8")
    else:
        diff_path.write_text(f"git diff unavailable\n{stderr}", encoding="utf-8")
    artifacts.append(
        artifact_for(
            task_id,
            run_id,
            diff_path,
            ArtifactType.DIFF,
            "collector",
            run_dir,
        )
    )
    return artifacts
