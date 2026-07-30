from pathlib import Path

from agentbridge.domain.enums import TaskState
from agentbridge.executors.fake import FakeExecutor
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.verification_service import VerificationService
from tests.test_execution_service import prepared


def test_verification_passes_declared_command(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    ExecutionService(database, tmp_path / "runs").run(runtime, task, FakeExecutor())
    passed, results, report = VerificationService(database, tmp_path / "runs").verify(
        runtime, task
    )
    assert passed
    assert results[0].status.value == "PASS"
    assert report.max_claim_level.value == "EXECUTED"
    assert runtime.state == TaskState.COMPLETED


def test_verification_failure_routes_to_repair(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.acceptance[0].command = "python -c \"raise SystemExit(7)\""
    ExecutionService(database, tmp_path / "runs").run(runtime, task, FakeExecutor())
    passed, _, _ = VerificationService(database, tmp_path / "runs").verify(runtime, task)
    assert not passed
    assert runtime.state == TaskState.REPAIR_READY


def test_multiple_verification_results_round_trip(database, tmp_path: Path) -> None:
    task, runtime = prepared(database)
    task.acceptance.append(task.acceptance[0].model_copy(update={"id": "A2"}))
    ExecutionService(database, tmp_path / "runs").run(runtime, task, FakeExecutor())
    passed, results, _ = VerificationService(database, tmp_path / "runs").verify(runtime, task)
    assert passed and len(results) == 2
    from agentbridge.persistence.repository import AgentRepository
    with database.connect() as conn:
        persisted = AgentRepository(conn).latest_verification_results(runtime.run_id)
        artifacts = AgentRepository(conn).list_artifacts(runtime.run_id)
    assert len(persisted) == 2
    artifact_ids = {a.artifact_id for a in artifacts}
    assert all(r.artifact_id in artifact_ids for r in persisted)
