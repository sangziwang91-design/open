import pytest

from agentbridge.domain.enums import TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.errors import ConcurrentUpdateError
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.state_manager import StateManager
from tests.test_repository import sample_task


def test_stale_runtime_cannot_overwrite_state_or_append_event(database) -> None:
    task = sample_task()
    original = TaskRuntime(task_id=task.task_id)
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        AgentRepository(uow.conn).save_task(task, original)

    with database.connect() as conn:
        first = AgentRepository(conn).get_runtime(task.task_id)
    with database.connect() as conn:
        stale = AgentRepository(conn).get_runtime(task.task_id)

    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        StateManager(AgentRepository(uow.conn)).transition(
            first, TaskState.VALIDATING, "ValidationStarted", "first"
        )

    with pytest.raises(ConcurrentUpdateError), UnitOfWork(database) as uow:
        assert uow.conn is not None
        StateManager(AgentRepository(uow.conn)).transition(
            stale, TaskState.VALIDATING, "ValidationStarted", "stale"
        )

    with database.connect() as conn:
        repo = AgentRepository(conn)
        persisted = repo.get_runtime(task.task_id)
        events = repo.list_events(task.task_id)
    assert persisted.state == TaskState.VALIDATING
    assert persisted.revision == 1
    assert len(events) == 1
    assert stale.state == TaskState.RECEIVED
