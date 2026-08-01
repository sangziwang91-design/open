import json
import sys
import time
from pathlib import Path

import pytest

from agentbridge.domain.enums import (
    ArtifactType,
    AttemptStatus,
    PermissionMode,
    TaskState,
)
from agentbridge.errors import ExecutorPolicyError, ExecutorUnavailableError
from agentbridge.executors.opencode import OpenCodeExecutor, probe_opencode
from agentbridge.persistence.repository import AgentRepository
from agentbridge.services.execution_service import ExecutionService
from tests.test_execution_service import prepared
from tests.test_repository import sample_task

SHIM = f"""#!{sys.executable}
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if "--version" in sys.argv:
    print(os.environ.get("OPENCODE_SHIM_VERSION", "1.18.10"))
    raise SystemExit(0)
if "--help" in sys.argv:
    print("--format --dir --agent --title")
    raise SystemExit(0)

capture = os.environ.get("OPENCODE_SHIM_CAPTURE")
if capture:
    Path(capture).write_text(
        json.dumps(
            {{
                "argv": sys.argv[1:],
                "cwd": os.getcwd(),
                "config": os.environ.get("OPENCODE_CONFIG_CONTENT"),
                "autoupdate": os.environ.get("OPENCODE_DISABLE_AUTOUPDATE"),
                "share": os.environ.get("OPENCODE_DISABLE_SHARE"),
            }}
        ),
        encoding="utf-8",
    )

mode = os.environ.get("OPENCODE_SHIM_MODE", "success")
if mode == "sleep":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    child_path = os.environ.get("OPENCODE_SHIM_CHILD")
    if child_path:
        Path(child_path).write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)
if mode == "fail":
    print("injected failure", file=sys.stderr)
    raise SystemExit(7)

Path("result.txt").write_text("created by shim", encoding="utf-8")
print('{{"type":"text","text":"shim completed"}}')
"""


def make_shim(tmp_path: Path) -> Path:
    path = tmp_path / "opencode-shim"
    path.write_text(SHIM, encoding="utf-8")
    path.chmod(0o755)
    return path


def authorize_opencode(task, workspace: Path) -> None:
    task.target.executor_id = "opencode"
    task.target.workspace = str(workspace)
    task.scope.include = ["."]
    task.scope.exclude = []
    task.permissions.file_write.mode = PermissionMode.ALLOW
    task.permissions.delete.mode = PermissionMode.ALLOW
    task.permissions.network.mode = PermissionMode.ALLOW
    task.permissions.shell.mode = PermissionMode.ALLOW


def test_missing_opencode_is_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agentbridge.executors.opencode.shutil.which", lambda _: None)
    with pytest.raises(ExecutorUnavailableError, match="not found"):
        OpenCodeExecutor().prepare(sample_task(), tmp_path)


def test_probe_rejects_unsupported_version(
    monkeypatch, tmp_path: Path
) -> None:
    shim = make_shim(tmp_path)
    monkeypatch.setenv("OPENCODE_SHIM_VERSION", "1.0.99")
    with pytest.raises(ExecutorUnavailableError, match="too old"):
        probe_opencode(str(shim))


def test_narrow_scope_is_rejected_before_launch(tmp_path: Path) -> None:
    task = sample_task()
    task.scope.include = ["src"]
    with pytest.raises(ExecutorPolicyError, match="whole-workspace"):
        OpenCodeExecutor().prepare(task, tmp_path / "run")


def test_invalid_inline_config_is_rejected(
    monkeypatch, tmp_path: Path
) -> None:
    shim = make_shim(tmp_path)
    task = sample_task()
    authorize_opencode(task, tmp_path)
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", "not-json")
    with pytest.raises(ExecutorPolicyError, match="JSON object"):
        OpenCodeExecutor(str(shim)).prepare(task, tmp_path / "run")


def test_real_subprocess_contract_and_policy_injection(
    monkeypatch, tmp_path: Path
) -> None:
    shim = make_shim(tmp_path)
    capture = tmp_path / "capture.json"
    monkeypatch.setenv("OPENCODE_SHIM_CAPTURE", str(capture))
    monkeypatch.setenv(
        "OPENCODE_CONFIG_CONTENT",
        json.dumps(
            {
                "model": "test/provider-model",
                "permission": "allow",
                "agent": {
                    "build": {
                        "model": "test/provider-model",
                        "permission": "allow",
                    }
                },
            }
        ),
    )
    task = sample_task()
    authorize_opencode(task, tmp_path)
    executor = OpenCodeExecutor(str(shim))

    context = executor.prepare(task, tmp_path / "run")
    assert context["opencode_version"] == "1.18.10"
    assert context["policy_hash"]
    policy_path = Path(context["policy_path"])
    assert executor.start(context) > 0
    assert "_environment" not in context
    assert executor.wait(timeout=5) == 0
    output = executor.collect()

    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["argv"] == [
        "--pure",
        "run",
        "--format",
        "json",
        "--agent",
        "build",
        "--title",
        task.task_id,
        "--dir",
        str(tmp_path.resolve()),
        task.goal,
    ]
    assert captured["cwd"] == str(tmp_path.resolve())
    assert captured["autoupdate"] == "1"
    assert captured["share"] == "1"
    config = json.loads(captured["config"])
    assert config["model"] == "test/provider-model"
    assert config["permission"]["*"] == "deny"
    assert config["permission"]["external_directory"] == "deny"
    assert config["permission"]["task"] == "deny"
    assert config["permission"]["edit"]["*.env"] == "deny"
    assert list(config["permission"]["edit"]) == [
        "*",
        "*.env",
        "*.env.*",
        "*.env.example",
    ]
    assert config["agent"]["build"]["model"] == "test/provider-model"
    assert config["agent"]["build"]["permission"] == config["permission"]
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["required_permissions"] == [
        "file_write",
        "delete",
        "network",
        "shell",
    ]
    assert policy["opencode_permission"] == config["permission"]
    assert "test/provider-model" not in policy_path.read_text(encoding="utf-8")
    assert Path(output["stdout_path"]).read_text(encoding="utf-8").strip() == (
        '{"type":"text","text":"shim completed"}'
    )
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "created by shim"
    assert "OPENCODE_CONFIG_CONTENT" not in Path(
        output["command_path"]
    ).read_text(encoding="utf-8")


def test_timeout_kills_subprocess_group_and_persists_attempt(
    monkeypatch, database, tmp_path: Path
) -> None:
    shim = make_shim(tmp_path)
    child_path = tmp_path / "child.pid"
    monkeypatch.setenv("OPENCODE_SHIM_MODE", "sleep")
    monkeypatch.setenv("OPENCODE_SHIM_CHILD", str(child_path))
    task, runtime = prepared(database)
    authorize_opencode(task, tmp_path)
    task.budget.timeout_seconds = 1

    started = time.monotonic()
    ok = ExecutionService(database, tmp_path / "runs").run(
        runtime, task, OpenCodeExecutor(str(shim))
    )
    duration = time.monotonic() - started

    assert not ok
    assert duration < 8
    assert runtime.state == TaskState.RECOVERY_REQUIRED
    with database.connect() as conn:
        repo = AgentRepository(conn)
        attempt = repo.latest_attempt(runtime.run_id)
        artifacts = repo.list_artifacts(runtime.run_id)
    assert attempt is not None
    assert attempt.status == AttemptStatus.TIMED_OUT
    assert attempt.finished_at is not None
    assert {artifact.type for artifact in artifacts} == {
        ArtifactType.BASELINE,
        ArtifactType.COMMAND,
        ArtifactType.POLICY,
        ArtifactType.STDOUT,
        ArtifactType.STDERR,
        ArtifactType.DIFF,
    }

    if Path("/proc").is_dir() and child_path.exists():
        child_pid = int(child_path.read_text(encoding="utf-8"))
        for _ in range(40):
            status = Path(f"/proc/{child_pid}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.05)
        else:
            pytest.fail("OpenCode child process remained active after timeout")
