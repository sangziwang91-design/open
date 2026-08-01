import platform
import sqlite3
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
import yaml

from agentbridge import __version__
from agentbridge.domain.capability import CapabilitySnapshot
from agentbridge.domain.enums import AttemptStatus, TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.domain.verification import ClaimReport
from agentbridge.errors import TaskNotFoundError
from agentbridge.executors.fake import FakeExecutor
from agentbridge.executors.opencode import OpenCodeExecutor, probe_opencode
from agentbridge.feedback.renderer import to_markdown, to_yaml
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.feedback_service import FeedbackService
from agentbridge.services.state_manager import StateManager
from agentbridge.services.verification_service import VerificationService

app = typer.Typer(
    no_args_is_help=True,
    invoke_without_command=True,
    help="Evidence-gated control plane for personal agents.",
)


class ExecutorName(str, Enum):
    FAKE = "fake"
    OPENCODE = "opencode"


def _database(path: Path) -> Database:
    db = Database(path)
    db.initialize()
    return db


def _load(db: Database, task_id: str) -> tuple[TaskEnvelope, TaskRuntime]:
    with db.connect() as conn:
        repo = AgentRepository(conn)
        return repo.get_envelope(task_id), repo.get_runtime(task_id)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit.", is_eager=True),
    ] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command("init")
def initialize(
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
) -> None:
    _database(db)
    typer.echo(f"Initialized: {db.resolve()}")


@app.command()
def doctor(
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
    opencode_executable: Annotated[
        str,
        typer.Option(
            "--opencode-executable",
            help="OpenCode executable name or absolute path to probe.",
        ),
    ] = "opencode",
    require_opencode: Annotated[
        bool,
        typer.Option(
            "--require-opencode",
            help="Exit nonzero unless the required OpenCode CLI contract is ready.",
        ),
    ] = False,
) -> None:
    database = _database(db)
    try:
        opencode: dict[str, str] = {
            "status": "READY",
            **probe_opencode(opencode_executable),
        }
    except Exception as exc:  # noqa: BLE001 - doctor must report, not crash
        opencode = {
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
    snapshot = CapabilitySnapshot(
        environment={
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "opencode": opencode,
        }
    )
    with UnitOfWork(database) as uow:
        AgentRepository(uow.connection).save_capability_snapshot(snapshot)
    typer.echo(yaml.safe_dump(snapshot.model_dump(mode="json"), sort_keys=False))
    if require_opencode and opencode["status"] != "READY":
        raise typer.Exit(1)


@app.command()
def submit(
    task_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
) -> None:
    data = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    envelope = TaskEnvelope.model_validate(data)
    runtime = TaskRuntime(
        task_id=envelope.task_id,
        executor_id=envelope.target.executor_id,
        workspace=envelope.target.workspace,
    )
    database = _database(db)
    with UnitOfWork(database) as uow:
        repo = AgentRepository(uow.connection)
        repo.save_task(envelope, runtime)
        manager = StateManager(repo)
        manager.transition(
            runtime, TaskState.VALIDATING, "ValidationStarted", "schema_validation"
        )
        manager.transition(runtime, TaskState.READY, "TaskReady", "task_envelope_valid")
    typer.echo(f"Task ID: {runtime.task_id}")
    typer.echo(f"Run ID: {runtime.run_id}")
    typer.echo(f"State: {runtime.state.value}")


@app.command()
def status(
    task_id: str,
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
) -> None:
    database = _database(db)
    try:
        with database.connect() as conn:
            repo = AgentRepository(conn)
            runtime = repo.get_runtime(task_id)
            events = repo.list_events(task_id)
    except TaskNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Task ID: {runtime.task_id}")
    typer.echo(f"Run ID: {runtime.run_id}")
    typer.echo(f"State: {runtime.state.value}")
    for event in events:
        typer.echo(
            f"{event.sequence_id}: {event.event_type} ({event.payload['to_state']})"
        )


@app.command()
def run(
    task_id: str,
    executor: Annotated[
        ExecutorName | None,
        typer.Option("--executor", help="Override the task's declared executor."),
    ] = None,
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path("data/runs"),
    opencode_executable: Annotated[
        str,
        typer.Option(
            "--opencode-executable",
            help="OpenCode executable name or absolute path.",
        ),
    ] = "opencode",
) -> None:
    database = _database(db)
    envelope, runtime = _load(database, task_id)
    if runtime.state not in {TaskState.READY, TaskState.REPAIR_READY}:
        typer.echo(
            f"Run requires READY or REPAIR_READY state, found {runtime.state.value}",
            err=True,
        )
        raise typer.Exit(2)
    executor_name = (
        executor.value if executor is not None else envelope.target.executor_id
    )
    selected = (
        FakeExecutor()
        if executor_name == ExecutorName.FAKE.value
        else OpenCodeExecutor(opencode_executable)
    )
    ok = ExecutionService(database, runs_dir).run(runtime, envelope, selected)
    typer.echo(f"State: {runtime.state.value}")
    if not ok:
        with database.connect() as conn:
            events = AgentRepository(conn).list_events(task_id)
        if events:
            typer.echo(f"Reason: {events[-1].payload.get('reason', 'unknown')}", err=True)
        raise typer.Exit(1)


@app.command()
def verify(
    task_id: str,
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path("data/runs"),
) -> None:
    database = _database(db)
    envelope, runtime = _load(database, task_id)
    if runtime.state != TaskState.WAITING_VERIFICATION:
        typer.echo(
            f"Verify requires WAITING_VERIFICATION state, found {runtime.state.value}",
            err=True,
        )
        raise typer.Exit(2)
    passed, results, report = VerificationService(database, runs_dir).verify(
        runtime, envelope
    )
    typer.echo(f"State: {runtime.state.value}")
    typer.echo(f"Claim level: {report.max_claim_level.value}")
    for result in results:
        typer.echo(f"{result.check_id}: {result.status.value} — {result.detail}")
    if not passed:
        raise typer.Exit(1)


@app.command()
def feedback(
    task_id: str,
    format: Annotated[
        str, typer.Option("--format", help="markdown or yaml")
    ] = "markdown",
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
) -> None:
    database = _database(db)
    with database.connect() as conn:
        repo = AgentRepository(conn)
        runtime = repo.get_runtime(task_id)
        results = repo.latest_verification_results(runtime.run_id)
        attempt = repo.latest_attempt(runtime.run_id)
    report = ClaimReport(
        forbidden_claims=[
            "The implementation is universally correct",
            "No undiscovered defects exist",
            "External effectiveness has been established",
        ]
    )
    envelope = FeedbackService.build(
        runtime, results, report, attempt.attempt_id if attempt else None
    )
    if format == "yaml":
        typer.echo(to_yaml(envelope))
    elif format == "markdown":
        typer.echo(to_markdown(envelope))
    else:
        typer.echo("format must be markdown or yaml", err=True)
        raise typer.Exit(2)


@app.command()
def recover(
    task_id: str,
    db: Annotated[Path, typer.Option("--db", help="SQLite database path.")] = Path(
        "agentbridge.db"
    ),
    force_inflight: Annotated[
        bool,
        typer.Option(
            "--force-inflight",
            help="Operator-confirmed recovery of an interrupted in-flight state.",
        ),
    ] = False,
) -> None:
    database = _database(db)
    _, runtime = _load(database, task_id)
    inflight_states = {
        TaskState.BASELINING,
        TaskState.DISPATCHING,
        TaskState.EXECUTING,
        TaskState.COLLECTING,
        TaskState.VERIFYING,
        TaskState.INTERRUPTED,
        TaskState.TIMED_OUT,
        TaskState.EXECUTOR_ERROR,
    }
    if runtime.state != TaskState.RECOVERY_REQUIRED and (
        not force_inflight or runtime.state not in inflight_states
    ):
        typer.echo(
            "Recover requires RECOVERY_REQUIRED; use --force-inflight only after "
            f"confirming an interrupted worker (found {runtime.state.value})",
            err=True,
        )
        raise typer.Exit(2)
    with UnitOfWork(database) as uow:
        repo = AgentRepository(uow.connection)
        manager = StateManager(repo)
        if runtime.state != TaskState.RECOVERY_REQUIRED:
            attempt = repo.latest_attempt(runtime.run_id)
            if attempt is not None and attempt.status in {
                AttemptStatus.CREATED,
                AttemptStatus.RUNNING,
            }:
                attempt.status = AttemptStatus.FAILED
                attempt.finished_at = datetime.now(UTC)
                attempt.signal = "OPERATOR_RECOVERY"
                repo.save_attempt(attempt)
            manager.force_recovery(
                runtime,
                "operator_confirmed_interrupted_inflight_state",
                actor="operator",
            )
        manager.transition(
            runtime, TaskState.READY, "RecoveryAccepted", "operator_retry"
        )
    typer.echo(f"State: {runtime.state.value}")


if __name__ == "__main__":
    app()
