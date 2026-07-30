import shlex
import sys
from pathlib import Path

from agentbridge.domain.enums import ArtifactType, TaskState
from agentbridge.executors.fake import FakeExecutor
from agentbridge.interpreters.artifact_collector import hash_file
from agentbridge.persistence.repository import AgentRepository
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.verification_service import VerificationService
from tests.test_execution_service import prepared


def test_acceptance_repair_can_rerun_same_run(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.acceptance[0] = task.acceptance[0].model_copy(
        update={"type": "fileexists", "command": None, "path": "result.txt"}
    )
    service = ExecutionService(database, tmp_path / "runs")
    verifier = VerificationService(database, tmp_path / "runs")

    assert service.run(runtime, task, FakeExecutor())
    passed, _, _ = verifier.verify(runtime, task)
    assert not passed
    assert runtime.state == TaskState.REPAIR_READY

    (tmp_path / "result.txt").write_text("fixed", encoding="utf-8")
    task.target.workspace = str(tmp_path)
    assert service.run(runtime, task, FakeExecutor())
    passed, _, _ = verifier.verify(runtime, task)
    assert passed
    assert runtime.state == TaskState.COMPLETED
    assert runtime.attempt_count == 2
    with database.connect() as conn:
        artifacts = AgentRepository(conn).list_artifacts(runtime.run_id)
    assert all(
        hash_file(Path(artifact.path)) == artifact.sha256 for artifact in artifacts
    )


def test_retry_budget_exhaustion_is_persisted(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.budget.max_executor_rounds = 1
    task.acceptance[0] = task.acceptance[0].model_copy(
        update={"type": "fileexists", "command": None, "path": "missing.txt"}
    )
    service = ExecutionService(database, tmp_path / "runs")
    verifier = VerificationService(database, tmp_path / "runs")

    assert service.run(runtime, task, FakeExecutor())
    passed, _, _ = verifier.verify(runtime, task)
    assert not passed
    assert not service.run(runtime, task, FakeExecutor())
    assert runtime.state == TaskState.WAITING_HUMAN
    assert runtime.attempt_count == 1


def test_command_verification_logs_are_immutable_across_retries(
    database, tmp_path: Path
) -> None:
    task, runtime = prepared(database)
    task.target.workspace = str(tmp_path)
    command = shlex.join(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "p=Path('sentinel'); print(p.exists()); "
                "raise SystemExit(0 if p.exists() else 1)"
            ),
        ]
    )
    task.acceptance[0] = task.acceptance[0].model_copy(update={"command": command})
    service = ExecutionService(database, tmp_path / "runs")
    verifier = VerificationService(database, tmp_path / "runs")

    assert service.run(runtime, task, FakeExecutor())
    assert not verifier.verify(runtime, task)[0]
    (tmp_path / "sentinel").write_text("fixed", encoding="utf-8")
    assert service.run(runtime, task, FakeExecutor())
    assert verifier.verify(runtime, task)[0]

    with database.connect() as conn:
        artifacts = AgentRepository(conn).list_artifacts(runtime.run_id)
    logs = [artifact for artifact in artifacts if artifact.type == ArtifactType.LOG]
    assert len(logs) == 2
    assert len({artifact.path for artifact in logs}) == 2
    assert all(hash_file(Path(artifact.path)) == artifact.sha256 for artifact in logs)
