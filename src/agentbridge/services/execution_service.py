# Imported only for the TimeoutExpired type.
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path

from agentbridge.domain.enums import AttemptStatus, PermissionMode, TaskState
from agentbridge.domain.execution_attempt import ExecutionAttempt
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.executors.base import Executor
from agentbridge.interpreters.artifact_collector import (
    capture_baseline,
    collect_execution_artifacts,
)
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.state_manager import StateManager


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionService:
    def __init__(self, database: Database, runs_dir: Path) -> None:
        self.database = database
        self.runs_dir = Path(runs_dir)

    def run(
        self, runtime: TaskRuntime, envelope: TaskEnvelope, executor: Executor
    ) -> bool:
        run_dir = self.runs_dir / runtime.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        attempt: ExecutionAttempt | None = None
        attempt_dir: Path | None = None
        try:
            with UnitOfWork(self.database) as uow:
                repo = AgentRepository(uow.connection)
                manager = StateManager(repo)
                if runtime.state not in {TaskState.READY, TaskState.REPAIR_READY}:
                    raise ValueError(
                        f"Execution requires READY or REPAIR_READY, found {runtime.state.value}"
                    )
                max_attempts = min(
                    envelope.budget.max_executor_rounds,
                    envelope.budget.max_retries_per_node + 1,
                )
                if runtime.attempt_count >= max_attempts:
                    if runtime.state == TaskState.READY:
                        manager.transition(
                            runtime,
                            TaskState.BASELINING,
                            "BaselineStarted",
                            "pre_execution",
                        )
                        target = TaskState.BLOCKED
                    else:
                        target = TaskState.WAITING_HUMAN
                    manager.transition(
                        runtime,
                        target,
                        "BudgetExhausted",
                        "execution_attempt_budget_exhausted",
                        extra={
                            "attempt_count": runtime.attempt_count,
                            "max_attempts": max_attempts,
                        },
                    )
                    return False
                if runtime.state == TaskState.READY:
                    manager.transition(
                        runtime,
                        TaskState.BASELINING,
                        "BaselineStarted",
                        "pre_execution",
                    )
                blocked_permissions = [
                    category
                    for category in executor.required_permissions
                    if envelope.permissions.effective(category) != PermissionMode.ALLOW
                ]
                if blocked_permissions:
                    target = (
                        TaskState.BLOCKED
                        if runtime.state == TaskState.BASELINING
                        else TaskState.WAITING_HUMAN
                    )
                    manager.transition(
                        runtime,
                        target,
                        "ExecutionBlocked",
                        "executor_permissions_not_allowed",
                        extra={"permissions": blocked_permissions},
                    )
                    return False
                attempt = ExecutionAttempt(
                    run_id=runtime.run_id,
                    task_id=runtime.task_id,
                    executor_id=executor.executor_id,
                )
                attempt_dir = (
                    run_dir
                    / f"attempt-{runtime.attempt_count + 1:04d}-{attempt.attempt_id}"
                )
                attempt_dir.mkdir(parents=True, exist_ok=False)
                repo.save_artifacts(
                    capture_baseline(
                        runtime.task_id,
                        runtime.run_id,
                        envelope.target.workspace,
                        attempt_dir,
                    )
                )
                runtime.executor_id = executor.executor_id
                runtime.workspace = envelope.target.workspace
                repo.update_runtime(runtime)
                prepared = executor.prepare(envelope, attempt_dir)
                manager.transition(
                    runtime,
                    TaskState.DISPATCHING,
                    "ExecutorPrepared",
                    "repair_command_built"
                    if runtime.state == TaskState.REPAIR_READY
                    else "command_built",
                    extra={"command_hash": prepared["command_hash"]},
                )

            if attempt is None or attempt_dir is None:
                raise RuntimeError("Execution attempt was not prepared")
            attempt.status = AttemptStatus.RUNNING
            with UnitOfWork(self.database) as uow:
                repo = AgentRepository(uow.connection)
                manager = StateManager(repo)
                repo.save_attempt(attempt)
                pid = executor.start(prepared)
                runtime.attempt_count += 1
                repo.update_runtime(runtime)
                manager.transition(
                    runtime,
                    TaskState.EXECUTING,
                    "ExecutorStarted",
                    "process_started",
                    extra={"pid": pid, "attempt_id": attempt.attempt_id},
                )

            exit_code = executor.wait(timeout=envelope.budget.timeout_seconds)
            raw = executor.collect()
            if raw.get("exit_code") != exit_code:
                raise ValueError("Executor wait and collect exit codes disagree")
            attempt.finished_at = utc_now()
            attempt.exit_code = exit_code
            attempt.signal = raw.get("signal")
            attempt.status = (
                AttemptStatus.FINISHED if exit_code == 0 else AttemptStatus.FAILED
            )

            with UnitOfWork(self.database) as uow:
                repo = AgentRepository(uow.connection)
                manager = StateManager(repo)
                repo.save_attempt(attempt)
                manager.transition(
                    runtime, TaskState.COLLECTING, "ExecutorFinished", "process_exited"
                )
                repo.save_artifacts(
                    collect_execution_artifacts(
                        runtime.task_id,
                        runtime.run_id,
                        raw,
                        attempt_dir,
                        envelope.target.workspace,
                    )
                )
                if exit_code == 0:
                    manager.transition(
                        runtime,
                        TaskState.WAITING_VERIFICATION,
                        "ArtifactsCollected",
                        "execution_evidence_collected",
                    )
                    return True
                manager.transition(
                    runtime,
                    TaskState.EXECUTOR_ERROR,
                    "ExecutorFailed",
                    f"exit_code={exit_code}",
                )
                manager.transition(
                    runtime,
                    TaskState.RECOVERY_REQUIRED,
                    "RecoveryRequired",
                    "executor_failure",
                )
                return False
        except subprocess.TimeoutExpired:
            cancel_error = self._cancel_if_running(executor)
            if attempt is not None:
                attempt.finished_at = utc_now()
                attempt.status = AttemptStatus.TIMED_OUT
            reason = "timeout" + (
                f"; cancel_error={cancel_error}" if cancel_error else ""
            )
            self._record_timeout(runtime, attempt, reason)
            return False
        except Exception as exc:  # noqa: BLE001 - executor boundary must persist all failures
            cancel_error = self._cancel_if_running(executor)
            if attempt is not None:
                attempt.finished_at = utc_now()
                attempt.status = AttemptStatus.FAILED
            reason = f"{type(exc).__name__}: {str(exc)[:500]}"
            if cancel_error:
                reason += f"; cancel_error={cancel_error}"
            try:
                self._record_forced_recovery(runtime, attempt, reason)
            except Exception as recovery_exc:
                raise RuntimeError(
                    "Execution failed and recovery could not be persisted"
                ) from recovery_exc
            return False

    @staticmethod
    def _cancel_if_running(executor: Executor) -> str | None:
        try:
            if executor.poll():
                executor.cancel()
        except Exception as exc:  # noqa: BLE001 - best-effort cancellation boundary
            return f"{type(exc).__name__}: {str(exc)[:200]}"
        return None

    @staticmethod
    def _sync_runtime(target: TaskRuntime, source: TaskRuntime) -> None:
        for field in TaskRuntime.model_fields:
            setattr(target, field, getattr(source, field))

    def _record_forced_recovery(
        self,
        runtime: TaskRuntime,
        attempt: ExecutionAttempt | None,
        reason: str,
    ) -> None:
        with UnitOfWork(self.database) as uow:
            repo = AgentRepository(uow.connection)
            persisted = repo.get_runtime_by_run(runtime.run_id)
            if attempt is not None:
                repo.save_attempt(attempt)
            StateManager(repo).force_recovery(persisted, reason)
        self._sync_runtime(runtime, persisted)

    def _record_timeout(
        self,
        runtime: TaskRuntime,
        attempt: ExecutionAttempt | None,
        reason: str,
    ) -> None:
        with UnitOfWork(self.database) as uow:
            repo = AgentRepository(uow.connection)
            manager = StateManager(repo)
            persisted = repo.get_runtime_by_run(runtime.run_id)
            if attempt is not None:
                repo.save_attempt(attempt)
            if persisted.state == TaskState.EXECUTING:
                manager.transition(
                    persisted,
                    TaskState.TIMED_OUT,
                    "ExecutionTimedOut",
                    reason,
                )
                manager.transition(
                    persisted,
                    TaskState.RECOVERY_REQUIRED,
                    "RecoveryRequired",
                    "timeout",
                )
            else:
                manager.force_recovery(persisted, reason)
        self._sync_runtime(runtime, persisted)
