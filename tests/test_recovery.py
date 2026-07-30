from agentbridge.domain.enums import TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.state_manager import StateManager
from tests.test_repository import sample_task


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
