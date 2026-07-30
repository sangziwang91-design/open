import subprocess
from datetime import datetime, timezone
from pathlib import Path

from agentbridge.domain.enums import AttemptStatus, TaskState
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
    return datetime.now(timezone.utc)


class ExecutionService:
    def __init__(self, database: Database, runs_dir: Path) -> None:
        self.database = database
        self.runs_dir = Path(runs_dir)

    def run(self, runtime: TaskRuntime, envelope: TaskEnvelope, executor: Executor) -> bool:
        run_dir = self.runs_dir / runtime.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        attempt: ExecutionAttempt | None = None
        try:
            with UnitOfWork(self.database) as uow:
                assert uow.conn is not None
                repo = AgentRepository(uow.conn)
                manager = StateManager(repo)
                manager.transition(runtime, TaskState.BASELINING, "BaselineStarted", "pre_execution")
                repo.save_artifacts(
                    capture_baseline(runtime.task_id, runtime.run_id, envelope.target.workspace, run_dir)
                )
                runtime.executor_id = executor.executor_id
                runtime.workspace = envelope.target.workspace
                repo.update_runtime(runtime)
                prepared = executor.prepare(envelope, run_dir)
                manager.transition(
                    runtime,
                    TaskState.DISPATCHING,
                    "ExecutorPrepared",
                    "command_built",
                    extra={"command_hash": prepared["command_hash"]},
                )

            attempt = ExecutionAttempt(
                run_id=runtime.run_id,
                task_id=runtime.task_id,
                executor_id=executor.executor_id,
                status=AttemptStatus.RUNNING,
            )
            with UnitOfWork(self.database) as uow:
                assert uow.conn is not None
                repo = AgentRepository(uow.conn)
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
            attempt.finished_at = utc_now()
            attempt.exit_code = exit_code
            attempt.status = AttemptStatus.FINISHED if exit_code == 0 else AttemptStatus.FAILED

            with UnitOfWork(self.database) as uow:
                assert uow.conn is not None
                repo = AgentRepository(uow.conn)
                manager = StateManager(repo)
                repo.save_attempt(attempt)
                manager.transition(runtime, TaskState.COLLECTING, "ExecutorFinished", "process_exited")
                repo.save_artifacts(
                    collect_execution_artifacts(runtime.task_id, runtime.run_id, raw, run_dir)
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
            executor.cancel()
            if attempt is not None:
                attempt.finished_at = utc_now()
                attempt.status = AttemptStatus.TIMED_OUT
            with UnitOfWork(self.database) as uow:
                assert uow.conn is not None
                repo = AgentRepository(uow.conn)
                manager = StateManager(repo)
                if attempt is not None:
                    repo.save_attempt(attempt)
                manager.transition(runtime, TaskState.TIMED_OUT, "ExecutionTimedOut", "timeout")
                manager.transition(
                    runtime, TaskState.RECOVERY_REQUIRED, "RecoveryRequired", "timeout"
                )
            return False
        except Exception as exc:
            try:
                with UnitOfWork(self.database) as uow:
                    assert uow.conn is not None
                    repo = AgentRepository(uow.conn)
                    StateManager(repo).force_recovery(runtime, str(exc))
            except Exception:
                pass
            return False
