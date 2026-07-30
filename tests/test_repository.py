from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork


def sample_task() -> TaskEnvelope:
    return TaskEnvelope.model_validate(
        {
            "title": "sample",
            "type": "engineering",
            "goal": "sample goal",
            "source": {"adapter": "test"},
            "target": {"executor_id": "fake", "workspace": "."},
            "acceptance": [{"id": "A1", "type": "command", "command": "python -V"}],
            "stop": {"success": "pass", "blocked": "blocked"},
        }
    )


def test_round_trip(database) -> None:
    task = sample_task()
    runtime = TaskRuntime(task_id=task.task_id)
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        AgentRepository(uow.conn).save_task(task, runtime)
    with database.connect() as conn:
        repo = AgentRepository(conn)
        assert repo.get_envelope(task.task_id).goal == task.goal
        assert repo.get_runtime(task.task_id).run_id == runtime.run_id
