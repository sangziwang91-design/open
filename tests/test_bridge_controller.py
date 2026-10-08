import threading
import time
from pathlib import Path

import pytest

from agentbridge.bridge.controller import (
    BridgeConfig,
    BridgeController,
    BridgeQueueFullError,
    compile_task,
)
from agentbridge.domain.enums import TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.executors.fake import FakeExecutor
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from tests.test_bridge_protocol import browser_task


def wait_for_terminal(controller: BridgeController, job_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = controller.store.get(job_id)
        if job is not None and job.status in {"FINISHED", "ERROR"}:
            return job
        time.sleep(0.02)
    raise AssertionError("bridge job did not reach a terminal state")


def fake_controller(tmp_path: Path) -> BridgeController:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return BridgeController(
        BridgeConfig(
            workspace=workspace,
            database=Database(tmp_path / "bridge.db"),
            runs_dir=tmp_path / "runs",
            executor_name="fake",
        )
    )


def test_worker_executes_and_verifies_full_job(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    controller.start()
    try:
        job, created = controller.submit(browser_task())
        assert created
        final = wait_for_terminal(controller, job.job_id)
        assert final.status == "FINISHED"
        assert final.result is not None
        assert final.result.status == "COMPLETED"
        assert final.result.state == "COMPLETED"
        assert final.result.claim_level.value == "EXECUTED"
        assert [(check.check_id, check.status) for check in final.result.checks] == [
            ("A1", "PASS")
        ]
        assert final.result.task_id and final.result.run_id
        assert all(not hasattr(item, "path") for item in final.result.artifacts)
    finally:
        controller.stop()


def test_failed_acceptance_returns_repair_evidence(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    controller.start()
    try:
        task = browser_task(
            request_id="REQ-fail",
            acceptance=[
                {
                    "id": "A1",
                    "type": "command",
                    "command": 'python -c "raise SystemExit(9)"',
                    "expected_exit_code": 0,
                }
            ],
        )
        job, _ = controller.submit(task)
        final = wait_for_terminal(controller, job.job_id)
        assert final.result is not None
        assert final.result.status == "FAILED"
        assert final.result.state == "REPAIR_READY"
        assert final.result.next_action == "REPAIR"
        assert final.result.checks[0].status == "FAIL"
        assert final.result.claim_level.value == "GENERATED"
    finally:
        controller.stop()


def test_executor_failure_returns_state_diagnostic(tmp_path: Path, monkeypatch) -> None:
    controller = fake_controller(tmp_path)
    monkeypatch.setattr(
        controller,
        "_executor",
        lambda: FakeExecutor(exit_code=7, stdout="executor explained failure\n"),
    )
    controller.start()
    try:
        job, _ = controller.submit(browser_task(request_id="REQ-executor-failure"))
        final = wait_for_terminal(controller, job.job_id)
        assert final.result is not None
        assert final.result.status == "BLOCKED"
        assert final.result.state == "RECOVERY_REQUIRED"
        assert "ExecutorFailed: exit_code=7" in final.result.error
        assert "executor explained failure" in final.result.executor_excerpt
        assert "Local state diagnostic" in final.result.summary
    finally:
        controller.stop()


def test_feedback_redacts_absolute_workspace_path(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    (controller.config.workspace / "present.txt").write_text("ok", encoding="utf-8")
    controller.start()
    try:
        task = browser_task(
            request_id="REQ-redact",
            acceptance=[{"id": "A1", "type": "fileexists", "path": "present.txt"}],
        )
        job, _ = controller.submit(task)
        final = wait_for_terminal(controller, job.job_id)
        assert final.result is not None
        serialized = final.result.model_dump_json()
        assert str(controller.config.workspace) not in serialized
        assert "<LOCAL_PATH>" in serialized
    finally:
        controller.stop()


def test_queued_job_survives_controller_restart(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    job, _ = controller.store.create_or_get(browser_task(request_id="REQ-restart"))
    assert job.status == "QUEUED"
    controller.start()
    try:
        final = wait_for_terminal(controller, job.job_id)
        assert final.status == "FINISHED"
        assert final.result is not None and final.result.status == "COMPLETED"
    finally:
        controller.stop()


def test_same_controller_instance_can_restart_after_stop(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    controller.start()
    controller.stop()
    controller.start()
    try:
        job, _ = controller.submit(browser_task(request_id="REQ-same-instance"))
        final = wait_for_terminal(controller, job.job_id)
        assert final.result is not None and final.result.status == "COMPLETED"
    finally:
        controller.stop()


def test_queue_limit_still_allows_idempotent_readback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    controller = BridgeController(
        BridgeConfig(
            workspace=workspace,
            database=Database(tmp_path / "bridge.db"),
            runs_dir=tmp_path / "runs",
            executor_name="fake",
            max_pending_jobs=1,
        )
    )
    first, _ = controller.submit(browser_task())
    duplicate, created = controller.submit(browser_task())
    assert not created and duplicate.job_id == first.job_id
    with pytest.raises(BridgeQueueFullError):
        controller.submit(browser_task(request_id="REQ-overflow"))


class BlockingExecutor(FakeExecutor):
    def __init__(self) -> None:
        super().__init__(exit_code=-9)
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def start(self, prepared_context):
        pid = super().start(prepared_context)
        self.started.set()
        return pid

    def wait(self, timeout=None):
        del timeout
        while self._running:
            time.sleep(0.01)
        assert self._context is not None
        run_dir = Path(self._context["run_dir"])
        (run_dir / "stdout.log").write_text("", encoding="utf-8")
        (run_dir / "stderr.log").write_text("cancelled", encoding="utf-8")
        return self.exit_code

    def cancel(self) -> None:
        self.cancelled.set()
        super().cancel()


def test_stop_cancels_active_executor_and_persists_result(
    tmp_path: Path, monkeypatch
) -> None:
    controller = fake_controller(tmp_path)
    blocking = BlockingExecutor()
    monkeypatch.setattr(controller, "_executor", lambda: blocking)
    controller.start()
    job, _ = controller.submit(browser_task(request_id="REQ-cancel"))
    assert blocking.started.wait(timeout=2)
    controller.stop(timeout=3)
    assert blocking.cancelled.is_set()
    final = controller.store.get(job.job_id)
    assert final is not None and final.status == "FINISHED"
    assert final.result is not None
    assert final.result.status == "BLOCKED"
    assert final.result.state == "RECOVERY_REQUIRED"


def test_controller_boundary_error_forces_core_runtime_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    controller = fake_controller(tmp_path)

    def fail_executor():
        raise RuntimeError("injected controller boundary error")

    monkeypatch.setattr(controller, "_executor", fail_executor)
    controller.start()
    try:
        job, _ = controller.submit(browser_task(request_id="REQ-boundary-error"))
        final = wait_for_terminal(controller, job.job_id)
        assert final.status == "ERROR"
        assert final.result is not None
        assert final.result.state == "RECOVERY_REQUIRED"
        assert final.run_id is not None
        with controller.config.database.connect() as conn:
            runtime = AgentRepository(conn).get_runtime_by_run(final.run_id)
        assert runtime.state == TaskState.RECOVERY_REQUIRED
    finally:
        controller.stop()


def test_startup_marks_linked_core_run_recovery_required(tmp_path: Path) -> None:
    controller = fake_controller(tmp_path)
    task = browser_task(request_id="REQ-core-recovery")
    job, _ = controller.store.create_or_get(task)
    assert controller.store.claim(job.job_id) is not None
    envelope = compile_task(task, controller.config)
    runtime = TaskRuntime(task_id=envelope.task_id)
    with UnitOfWork(controller.config.database) as uow:
        AgentRepository(uow.connection).save_task(envelope, runtime)
    controller.store.bind_run(job.job_id, runtime.task_id, runtime.run_id)
    controller.start()
    try:
        with controller.config.database.connect() as conn:
            recovered = AgentRepository(conn).get_runtime_by_run(runtime.run_id)
        assert recovered.state == TaskState.RECOVERY_REQUIRED
    finally:
        controller.stop()
