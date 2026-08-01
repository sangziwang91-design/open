from pathlib import Path

from agentbridge.domain.enums import ArtifactType, AttemptStatus, TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.executors.fake import FakeExecutor
from agentbridge.executors.opencode import OpenCodeExecutor
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.state_manager import StateManager
from tests.test_repository import sample_task


def prepared(database):
    task = sample_task()
    runtime = TaskRuntime(task_id=task.task_id)
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        repo = AgentRepository(uow.conn)
        repo.save_task(task, runtime)
        manager = StateManager(repo)
        manager.transition(runtime, TaskState.VALIDATING, "ValidationStarted", "test")
        manager.transition(runtime, TaskState.READY, "TaskReady", "test")
    return task, runtime


def test_success_reaches_waiting_verification(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    assert ExecutionService(database, tmp_path / "runs").run(
        runtime, task, FakeExecutor()
    )
    assert runtime.state == TaskState.WAITING_VERIFICATION
    with database.connect() as conn:
        assert len(AgentRepository(conn).list_artifacts(runtime.run_id)) >= 4


def test_failure_reaches_recovery(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    assert not ExecutionService(database, tmp_path / "runs").run(
        runtime, task, FakeExecutor(exit_code=2)
    )
    assert runtime.state == TaskState.RECOVERY_REQUIRED


def test_executor_permissions_block_before_prepare(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.target.executor_id = "opencode"
    task.permissions.shell.mode = "deny"
    assert not ExecutionService(database, tmp_path / "runs").run(
        runtime, task, OpenCodeExecutor()
    )
    assert runtime.state == TaskState.BLOCKED
    with database.connect() as conn:
        repo = AgentRepository(conn)
        assert repo.latest_attempt(runtime.run_id) is None
        assert repo.list_events(task.task_id)[-1].event_type == "ExecutionBlocked"


def test_opencode_requires_explicit_delete_and_network_permissions(
    database, tmp_path: Path
) -> None:
    task, runtime = prepared(database)
    task.target.executor_id = "opencode"
    assert not ExecutionService(database, tmp_path / "runs").run(
        runtime, task, OpenCodeExecutor()
    )
    assert runtime.state == TaskState.BLOCKED
    with database.connect() as conn:
        event = AgentRepository(conn).list_events(task.task_id)[-1]
    assert event.event_type == "ExecutionBlocked"
    assert event.payload["permissions"] == ["delete", "network"]


class BrokenCollectExecutor(FakeExecutor):
    def collect(self):
        raise RuntimeError("collector failed")


class BrokenPrepareExecutor(FakeExecutor):
    def prepare(self, envelope, run_dir):
        raise RuntimeError("prepare failed")


def test_prepare_failure_consumes_attempt_budget(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.budget.max_executor_rounds = 1
    task.budget.max_retries_per_node = 0
    service = ExecutionService(database, tmp_path / "runs")

    assert not service.run(runtime, task, BrokenPrepareExecutor())
    assert runtime.state == TaskState.RECOVERY_REQUIRED
    assert runtime.attempt_count == 1
    with database.connect() as conn:
        repo = AgentRepository(conn)
        attempt = repo.latest_attempt(runtime.run_id)
        artifacts = repo.list_artifacts(runtime.run_id)
    assert attempt is not None
    assert attempt.status == AttemptStatus.FAILED
    assert {artifact.type for artifact in artifacts} == {
        ArtifactType.BASELINE,
        ArtifactType.DIFF,
    }

    with UnitOfWork(database) as uow:
        StateManager(AgentRepository(uow.connection)).transition(
            runtime, TaskState.READY, "RecoveryAccepted", "test_retry"
        )
    assert not service.run(runtime, task, BrokenPrepareExecutor())
    assert runtime.state == TaskState.BLOCKED
    assert runtime.attempt_count == 1
    with database.connect() as conn:
        repo = AgentRepository(conn)
        attempts = conn.execute(
            "SELECT COUNT(*) FROM execution_attempts WHERE run_id=?",
            (runtime.run_id,),
        ).fetchone()[0]
        event = repo.list_events(task.task_id)[-1]
    assert attempts == 1
    assert event.event_type == "BudgetExhausted"


def test_collection_error_finalizes_attempt_and_records_recovery(
    database, tmp_path: Path
) -> None:
    task, runtime = prepared(database)
    assert not ExecutionService(database, tmp_path / "runs").run(
        runtime, task, BrokenCollectExecutor()
    )
    assert runtime.state == TaskState.RECOVERY_REQUIRED
    with database.connect() as conn:
        repo = AgentRepository(conn)
        attempt = repo.latest_attempt(runtime.run_id)
        assert attempt is not None
        assert attempt.status == AttemptStatus.FAILED
        assert attempt.finished_at is not None
        events = repo.list_events(task.task_id)
        artifacts = repo.list_artifacts(runtime.run_id)
    assert events[-1].event_type == "ForcedRecovery"
    assert "collector failed" in events[-1].payload["reason"]
    assert {artifact.type for artifact in artifacts} == {
        ArtifactType.BASELINE,
        ArtifactType.COMMAND,
        ArtifactType.STDOUT,
        ArtifactType.STDERR,
        ArtifactType.DIFF,
    }
