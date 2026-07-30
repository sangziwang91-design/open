from pathlib import Path

from agentbridge.domain.enums import AttemptStatus, TaskState
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


class BrokenCollectExecutor(FakeExecutor):
    def collect(self):
        raise RuntimeError("collector failed")


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
    assert events[-1].event_type == "ForcedRecovery"
    assert "collector failed" in events[-1].payload["reason"]
