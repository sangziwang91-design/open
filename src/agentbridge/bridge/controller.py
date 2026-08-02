import os
import queue
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agentbridge.bridge.protocol import (
    BrainTaskMessage,
    BridgeArtifact,
    BridgeCheck,
    BridgeResultMessage,
)
from agentbridge.bridge.store import BridgeStore, StoredBridgeJob
from agentbridge.domain.enums import ArtifactType, PermissionMode, TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import (
    Budget,
    Permissions,
    Scope,
    Source,
    StopConditions,
    Target,
    TaskEnvelope,
)
from agentbridge.domain.verification import ClaimReport
from agentbridge.errors import TaskNotFoundError
from agentbridge.executors.base import Executor
from agentbridge.executors.fake import FakeExecutor
from agentbridge.executors.opencode import OpenCodeExecutor
from agentbridge.feedback.renderer import to_markdown
from agentbridge.interpreters.artifact_collector import validate_artifact_file
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.feedback_service import FeedbackService
from agentbridge.services.state_manager import StateManager
from agentbridge.services.verification_service import VerificationService

DEFAULT_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SHELL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USER",
        "USERPROFILE",
        "WINDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)

VERIFICATION_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)


def filtered_bridge_environment() -> dict[str, str]:
    allowed = VERIFICATION_ENVIRONMENT_ALLOWLIST
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


class BridgeQueueFullError(RuntimeError):
    """The bounded local bridge queue has no capacity."""


@dataclass(frozen=True)
class BridgeConfig:
    workspace: Path
    database: Database
    runs_dir: Path
    executor_name: Literal["fake", "opencode"] = "opencode"
    opencode_executable: str = "opencode"
    inherited_environment: frozenset[str] = field(default_factory=frozenset)
    max_timeout_seconds: int = 1800
    max_pending_jobs: int = 32

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve()
        if not workspace.is_dir():
            raise ValueError(f"bridge workspace is not a directory: {workspace}")
        if self.executor_name not in {"fake", "opencode"}:
            raise ValueError("bridge executor must be fake or opencode")
        if self.max_timeout_seconds < 1 or self.max_timeout_seconds > 3600:
            raise ValueError("max_timeout_seconds must be between 1 and 3600")
        if self.max_pending_jobs < 1 or self.max_pending_jobs > 1000:
            raise ValueError("max_pending_jobs must be between 1 and 1000")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "runs_dir", self.runs_dir.resolve())


def task_id_for(task: BrainTaskMessage) -> str:
    return f"TASK-BRIDGE-{task.request_hash()[:12].upper()}"


def compile_task(task: BrainTaskMessage, config: BridgeConfig) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=task_id_for(task),
        title=task.title,
        type="engineering",
        goal=task.goal,
        source=Source(adapter="chatgpt-web", conversation_ref=task.session_id),
        target=Target(
            executor_id=config.executor_name,
            workspace=str(config.workspace),
        ),
        scope=Scope(include=["."], exclude=[]),
        constraints=task.constraints,
        acceptance=task.acceptance,
        permissions=Permissions.model_validate(
            {
                "file_write": {"mode": PermissionMode.ALLOW},
                "delete": {"mode": PermissionMode.ALLOW},
                "network": {"mode": PermissionMode.ALLOW},
                "shell": {"mode": PermissionMode.ALLOW},
            }
        ),
        budget=Budget(
            max_executor_rounds=1,
            max_retries_per_node=0,
            timeout_seconds=min(task.timeout_seconds, config.max_timeout_seconds),
        ),
        stop=StopConditions(
            success="all declared acceptance checks pass",
            blocked="return evidence and wait for a new browser-brain decision",
        ),
    )


class BridgeController:
    """Single-workspace, serial, persistent execution controller."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.config.database.initialize()
        self.store = BridgeStore(config.database)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._executor_lock = threading.Lock()
        self._active_executor: Executor | None = None
        self._shutdown_error: str | None = None

    def start(self) -> int:
        if self._thread is not None and self._thread.is_alive():
            return 0
        self._queue = queue.Queue()
        interrupted = self.store.running()
        recovered = self.store.recover_interrupted()
        for job in interrupted:
            self._mark_interrupted_runtime(job)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="agentbridge-worker",
            daemon=True,
        )
        self._thread.start()
        for job in self.store.queued():
            self._queue.put(job.job_id)
        return recovered

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._queue.put(None)
        deadline = time.monotonic() + timeout
        while self._thread is not None and self._thread.is_alive():
            with self._executor_lock:
                active = self._active_executor
            if active is not None:
                try:
                    if active.poll():
                        active.cancel()
                except Exception as exc:  # noqa: BLE001 - shutdown remains best effort
                    self._shutdown_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._thread.join(timeout=min(0.1, remaining))

    def submit(self, task: BrainTaskMessage) -> tuple[StoredBridgeJob, bool]:
        existing = self.store.get_by_request(task.session_id, task.request_id)
        if (
            existing is None
            and self.store.active_count() >= self.config.max_pending_jobs
        ):
            raise BridgeQueueFullError("bridge queue is full")
        job, created = self.store.create_or_get(task)
        if created:
            self._queue.put(job.job_id)
        return job, created

    def process_job(self, job_id: str) -> None:
        job = self.store.claim(job_id)
        if job is None:
            return
        runtime: TaskRuntime | None = None
        try:
            envelope = compile_task(job.task, self.config)
            runtime = TaskRuntime(
                task_id=envelope.task_id,
                executor_id=envelope.target.executor_id,
                workspace=envelope.target.workspace,
            )
            with UnitOfWork(self.config.database) as uow:
                repo = AgentRepository(uow.connection)
                repo.save_task(envelope, runtime)
                manager = StateManager(repo)
                manager.transition(
                    runtime,
                    TaskState.VALIDATING,
                    "ValidationStarted",
                    "browser_protocol_valid",
                    actor="bridge",
                )
                manager.transition(
                    runtime,
                    TaskState.READY,
                    "TaskReady",
                    "local_authority_applied",
                    actor="bridge",
                )
            self.store.bind_run(job.job_id, runtime.task_id, runtime.run_id)
            executor = self._executor()
            with self._executor_lock:
                self._active_executor = executor
            try:
                executed = ExecutionService(
                    self.config.database, self.config.runs_dir
                ).run(runtime, envelope, executor)
            finally:
                with self._executor_lock:
                    self._active_executor = None
            report = ClaimReport()
            if executed and runtime.state == TaskState.WAITING_VERIFICATION:
                _, results, report = VerificationService(
                    self.config.database,
                    self.config.runs_dir,
                    command_environment=filtered_bridge_environment(),
                ).verify(runtime, envelope)
            else:
                results = []
            result = self._build_result(job, runtime, results, report)
            self.store.finish(job.job_id, result)
        except Exception as exc:  # noqa: BLE001 - persist the bridge boundary failure
            error = self._redact_local_paths(f"{type(exc).__name__}: {str(exc)[:900]}")
            if runtime is not None:
                recovered = self._force_runtime_recovery(runtime.run_id, error)
                if recovered is not None:
                    runtime = recovered
            result = BridgeResultMessage(
                session_id=job.task.session_id,
                request_id=job.task.request_id,
                job_id=job.job_id,
                task_id=runtime.task_id if runtime else None,
                run_id=runtime.run_id if runtime else None,
                status="BLOCKED",
                state=(runtime.state.value if runtime else "BRIDGE_ERROR"),
                summary="The local bridge could not complete this request.",
                next_action="INPUT",
                requires_human_decision=True,
                question_to_human="Inspect the local bridge error before submitting a new request.",
                error=error,
            )
            self.store.fail(job.job_id, result, error)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self.process_job(job_id)
            finally:
                self._queue.task_done()

    def _executor(self) -> Executor:
        if self.config.executor_name == "fake":
            return FakeExecutor()
        environment = DEFAULT_ENVIRONMENT_ALLOWLIST | frozenset(
            value.upper() for value in self.config.inherited_environment
        )
        return OpenCodeExecutor(
            self.config.opencode_executable,
            environment_allowlist=environment,
        )

    def _mark_interrupted_runtime(self, job: StoredBridgeJob) -> None:
        if not job.run_id:
            return
        self._force_runtime_recovery(
            job.run_id,
            "bridge_controller_interrupted",
        )

    def _force_runtime_recovery(self, run_id: str, reason: str) -> TaskRuntime | None:
        try:
            with UnitOfWork(self.config.database) as uow:
                repo = AgentRepository(uow.connection)
                runtime = repo.get_runtime_by_run(run_id)
                if runtime.state not in {
                    TaskState.COMPLETED,
                    TaskState.CLOSED,
                    TaskState.ABORTED,
                    TaskState.RECOVERY_REQUIRED,
                }:
                    StateManager(repo).force_recovery(
                        runtime,
                        reason,
                        actor="bridge",
                    )
                return runtime
        except TaskNotFoundError:
            return None

    def _build_result(
        self,
        job: StoredBridgeJob,
        runtime: TaskRuntime,
        results: Iterable,
        report: ClaimReport,
    ) -> BridgeResultMessage:
        verification_results = list(results)
        with self.config.database.connect() as conn:
            repo = AgentRepository(conn)
            attempt = repo.latest_attempt(runtime.run_id)
            artifacts = repo.list_artifacts(runtime.run_id)
            events = repo.list_events(runtime.task_id)
        feedback = FeedbackService.build(
            runtime,
            verification_results,
            report,
            attempt.attempt_id if attempt else None,
        )
        excerpt = self._executor_excerpt(runtime.run_id, artifacts)
        diagnostic = (
            None
            if runtime.state == TaskState.COMPLETED
            else self._event_diagnostic(events)
        )
        checks = [
            BridgeCheck(
                check_id=result.check_id,
                status=result.status.value,
                detail=self._redact_local_paths(result.detail[:1000]),
            )
            for result in verification_results
        ]
        evidence = [
            BridgeArtifact(type=artifact.type.value, sha256=artifact.sha256)
            for artifact in artifacts
        ]
        summary = self._redact_local_paths(to_markdown(feedback))
        if diagnostic:
            summary += f"\nLocal state diagnostic: {diagnostic}\n"
        return BridgeResultMessage(
            session_id=job.task.session_id,
            request_id=job.task.request_id,
            job_id=job.job_id,
            task_id=runtime.task_id,
            run_id=runtime.run_id,
            status=feedback.status,
            state=runtime.state.value,
            summary=summary[:6000],
            checks=checks,
            artifacts=evidence,
            executor_excerpt=(self._redact_local_paths(excerpt) if excerpt else None),
            claim_level=report.max_claim_level,
            next_action=feedback.allowed_next_action,
            requires_human_decision=feedback.requires_human_decision,
            question_to_human=feedback.question_to_human,
            error=(diagnostic if runtime.state != TaskState.COMPLETED else None),
        )

    def _executor_excerpt(self, run_id: str, artifacts: Iterable) -> str | None:
        run_root = self.config.runs_dir / run_id
        parts: list[str] = []
        for artifact_type, label in (
            (ArtifactType.STDOUT, "stdout"),
            (ArtifactType.STDERR, "stderr"),
        ):
            artifact = next(
                (
                    item
                    for item in reversed(list(artifacts))
                    if item.type == artifact_type
                ),
                None,
            )
            if artifact is None:
                continue
            path, error = validate_artifact_file(artifact, run_root)
            if path is None or error is not None:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                parts.append(f"[{label}]\n{text}")
        combined = "\n\n".join(parts)
        return combined[-4000:] if combined else None

    def _event_diagnostic(self, events: Iterable) -> str | None:
        entries: list[str] = []
        for event in reversed(list(events)):
            reason = event.payload.get("reason")
            if reason and reason not in {
                "executor_failure",
                "execution_evidence_collected",
            }:
                entries.append(f"{event.event_type}: {reason}")
            if len(entries) == 2:
                break
        if not entries:
            return None
        return self._redact_local_paths("; ".join(reversed(entries)))[:2000]

    def _redact_local_paths(self, text: str) -> str:
        redacted = text
        workspace = self.config.workspace.resolve()
        candidates = {
            str(workspace),
            workspace.as_posix(),
            str(self.config.runs_dir.resolve()),
            self.config.runs_dir.resolve().as_posix(),
        }
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate:
                redacted = redacted.replace(candidate, "<LOCAL_PATH>")
        return redacted
