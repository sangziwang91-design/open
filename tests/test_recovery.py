from pathlib import Path

from typer.testing import CliRunner

from agentbridge.cli import app
from agentbridge.domain.enums import AttemptStatus, TaskState
from agentbridge.domain.execution_attempt import ExecutionAttempt
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.state_manager import StateManager
from tests.test_repository import sample_task

runner = CliRunner()


def test_forced_recovery_is_evented(database) -> None:
    task = sample_task()
    runtime = TaskRuntime(task_id=task.task_id)
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        repo = AgentRepository(uow.conn)
        repo.save_task(task, runtime)
        StateManager(repo).force_recovery(runtime, "simulated crash")
    with database.connect() as conn:
        events = AgentRepository(conn).list_events(task.task_id)
    assert runtime.state == TaskState.RECOVERY_REQUIRED
    assert events[-1].payload["forced"] is True


def test_force_inflight_recovery_finalizes_orphaned_attempt(tmp_path: Path) -> None:
    path = tmp_path / "recovery.db"
    from agentbridge.persistence.database import Database

    database = Database(path)
    database.initialize()
    task = sample_task()
    runtime = TaskRuntime(task_id=task.task_id)
    attempt = ExecutionAttempt(
        run_id=runtime.run_id,
        task_id=runtime.task_id,
        executor_id="fake",
        status=AttemptStatus.RUNNING,
    )
    with UnitOfWork(database) as uow:
        repo = AgentRepository(uow.connection)
        repo.save_task(task, runtime)
        manager = StateManager(repo)
        manager.transition(runtime, TaskState.VALIDATING, "ValidationStarted", "test")
        manager.transition(runtime, TaskState.READY, "TaskReady", "test")
        manager.transition(runtime, TaskState.BASELINING, "BaselineStarted", "test")
        manager.transition(runtime, TaskState.DISPATCHING, "ExecutorPrepared", "test")
        repo.save_attempt(attempt)
        manager.transition(runtime, TaskState.EXECUTING, "ExecutorStarted", "test")

    denied = runner.invoke(app, ["recover", task.task_id, "--db", str(path)])
    assert denied.exit_code == 2
    recovered = runner.invoke(
        app,
        ["recover", task.task_id, "--db", str(path), "--force-inflight"],
    )
    assert recovered.exit_code == 0, recovered.output
    with database.connect() as conn:
        repo = AgentRepository(conn)
        persisted = repo.get_runtime(task.task_id)
        saved_attempt = repo.latest_attempt(runtime.run_id)
        events = repo.list_events(task.task_id)
    assert persisted.state == TaskState.READY
    assert saved_attempt is not None
    assert saved_attempt.status == AttemptStatus.FAILED
    assert saved_attempt.finished_at is not None
    assert [event.event_type for event in events[-2:]] == [
        "ForcedRecovery",
        "RecoveryAccepted",
    ]
