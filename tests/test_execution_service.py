from pathlib import Path

from agentbridge.domain.enums import TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.executors.fake import FakeExecutor
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
    assert ExecutionService(database, tmp_path / "runs").run(runtime, task, FakeExecutor())
    assert runtime.state == TaskState.WAITING_VERIFICATION
    with database.connect() as conn:
        assert len(AgentRepository(conn).list_artifacts(runtime.run_id)) >= 4


def test_failure_reaches_recovery(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    assert not ExecutionService(database, tmp_path / "runs").run(
        runtime, task, FakeExecutor(exit_code=2)
    )
    assert runtime.state == TaskState.RECOVERY_REQUIRED
