import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentbridge.domain.enums import TaskState, VerificationStatus
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.executors.fake import FakeExecutor
from agentbridge.interpreters.artifact_collector import hash_file
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.state_manager import StateManager
from agentbridge.services.verification_service import VerificationService


def make_task(index: int, workspace: Path, acceptance_path: str) -> TaskEnvelope:
    return TaskEnvelope.model_validate(
        {
            "task_id": f"TASK-LONG-{index:06d}",
            "title": f"long-run cycle {index}",
            "type": "validation",
            "goal": f"execute bounded cycle {index}",
            "source": {"adapter": "long-run"},
            "target": {"executor_id": "fake", "workspace": str(workspace)},
            "acceptance": [{"id": "A1", "type": "fileexists", "path": acceptance_path}],
            "stop": {"success": "acceptance passed", "blocked": "record blocker"},
        }
    )


def submit_ready(database: Database, task: TaskEnvelope) -> TaskRuntime:
    runtime = TaskRuntime(
        task_id=task.task_id,
        executor_id=task.target.executor_id,
        workspace=task.target.workspace,
    )
    with UnitOfWork(database) as uow:
        repo = AgentRepository(uow.connection)
        repo.save_task(task, runtime)
        manager = StateManager(repo)
        manager.transition(
            runtime, TaskState.VALIDATING, "ValidationStarted", "long_run"
        )
        manager.transition(runtime, TaskState.READY, "TaskReady", "long_run")
    return runtime


def reload_task(database: Database, task_id: str) -> tuple[TaskEnvelope, TaskRuntime]:
    with database.connect() as conn:
        repo = AgentRepository(conn)
        return repo.get_envelope(task_id), repo.get_runtime(task_id)


def recover_executor_failure(database: Database, runtime: TaskRuntime) -> None:
    with UnitOfWork(database) as uow:
        StateManager(AgentRepository(uow.connection)).transition(
            runtime, TaskState.READY, "RecoveryAccepted", "long_run_retry"
        )


def run_concurrency_probe(root: Path, tasks: int, workers: int) -> dict[str, int | str]:
    path = root / "concurrency.db"
    database = Database(path)
    database.initialize()
    workspace = root / "concurrency-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "accepted.txt").write_text("ok", encoding="utf-8")

    def create(index: int) -> None:
        task = make_task(1_000_000 + index, workspace, "accepted.txt")
        submit_ready(database, task)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(create, range(tasks)))

    with database.connect() as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        ready_count = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE state='READY'"
        ).fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if (run_count, ready_count, event_count) != (tasks, tasks, tasks * 2):
        raise AssertionError("Concurrent submission counts are inconsistent")
    if integrity != "ok" or foreign_key_errors:
        raise AssertionError("Concurrent database integrity check failed")
    return {
        "tasks": tasks,
        "workers": workers,
        "events": event_count,
        "integrity": integrity,
        "foreign_key_errors": foreign_key_errors,
    }


def run_validation(
    root: Path,
    cycles: int = 500,
    restart_every: int = 25,
    fault_every: int = 17,
    repair_every: int = 19,
    concurrent_tasks: int = 100,
    workers: int = 8,
) -> dict[str, object]:
    if cycles < 1:
        raise ValueError("cycles must be positive")
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "accepted.txt").write_text("ok", encoding="utf-8")
    database = Database(root / "agentbridge.db")
    database.initialize()
    runs_dir = root / "runs"
    started = time.monotonic()
    fault_cycles = 0
    repair_cycles = 0

    for index in range(1, cycles + 1):
        repair_cycle = repair_every > 0 and index % repair_every == 0
        fault_cycle = not repair_cycle and fault_every > 0 and index % fault_every == 0
        acceptance_path = f"repair-{index}.txt" if repair_cycle else "accepted.txt"
        task = make_task(index, workspace, acceptance_path)
        runtime = submit_ready(database, task)

        if restart_every > 0 and index % restart_every == 0:
            database = Database(root / "agentbridge.db")
            database.initialize()
            task, runtime = reload_task(database, task.task_id)

        execution = ExecutionService(database, runs_dir)
        verification = VerificationService(database, runs_dir)
        if fault_cycle:
            fault_cycles += 1
            if execution.run(runtime, task, FakeExecutor(exit_code=9)):
                raise AssertionError("Injected executor failure unexpectedly passed")
            if runtime.state != TaskState.RECOVERY_REQUIRED:
                raise AssertionError("Executor failure did not require recovery")
            recover_executor_failure(database, runtime)

        if not execution.run(runtime, task, FakeExecutor()):
            raise AssertionError(f"Cycle {index} execution failed")

        if restart_every > 0 and index % restart_every == restart_every // 2:
            database = Database(root / "agentbridge.db")
            database.initialize()
            task, runtime = reload_task(database, task.task_id)
            verification = VerificationService(database, runs_dir)

        passed, _, _ = verification.verify(runtime, task)
        if repair_cycle:
            repair_cycles += 1
            if passed or runtime.state != TaskState.REPAIR_READY:
                raise AssertionError(
                    "Injected acceptance failure did not route to repair"
                )
            (workspace / acceptance_path).write_text("fixed", encoding="utf-8")
            if not ExecutionService(database, runs_dir).run(
                runtime, task, FakeExecutor(stdout="repair completed\n")
            ):
                raise AssertionError("Repair execution failed")
            passed, _, _ = VerificationService(database, runs_dir).verify(runtime, task)
        if not passed or runtime.state != TaskState.COMPLETED:
            raise AssertionError(f"Cycle {index} did not complete")

    database = Database(root / "agentbridge.db")
    database.initialize()
    bad_artifacts: list[str] = []
    bad_latest_results: list[str] = []
    with database.connect() as conn:
        repo = AgentRepository(conn)
        run_rows = conn.execute("SELECT run_id, task_id, state FROM runs").fetchall()
        artifact_rows = conn.execute("SELECT path, sha256 FROM artifacts").fetchall()
        for row in artifact_rows:
            path = Path(row["path"])
            if not path.is_file() or hash_file(path) != row["sha256"]:
                bad_artifacts.append(str(path))
        for row in run_rows:
            results = repo.latest_verification_results(row["run_id"])
            if not results or any(
                result.status != VerificationStatus.PASS for result in results
            ):
                bad_latest_results.append(row["task_id"])
        state_counts = {
            row["state"]: row["count"]
            for row in conn.execute(
                "SELECT state, COUNT(*) AS count FROM runs GROUP BY state"
            )
        }
        attempts = conn.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
        unfinished_attempts = conn.execute(
            "SELECT COUNT(*) FROM execution_attempts "
            "WHERE status IN ('CREATED', 'RUNNING')"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        artifacts = len(artifact_rows)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    if state_counts != {TaskState.COMPLETED.value: cycles}:
        raise AssertionError(f"Unexpected terminal states: {state_counts}")
    if unfinished_attempts:
        raise AssertionError(f"Unfinished attempts remain: {unfinished_attempts}")
    if bad_artifacts:
        raise AssertionError(f"Artifact integrity failures: {len(bad_artifacts)}")
    if bad_latest_results:
        raise AssertionError(f"Latest verification failures: {len(bad_latest_results)}")
    if integrity != "ok" or foreign_key_errors:
        raise AssertionError("Primary database integrity check failed")

    concurrency = run_concurrency_probe(root, concurrent_tasks, workers)
    duration = time.monotonic() - started
    return {
        "status": "PASS",
        "cycles": cycles,
        "fault_cycles": fault_cycles,
        "repair_cycles": repair_cycles,
        "restarts": cycles // restart_every if restart_every > 0 else 0,
        "attempts": attempts,
        "events": events,
        "artifacts": artifacts,
        "unfinished_attempts": unfinished_attempts,
        "artifact_integrity_failures": len(bad_artifacts),
        "latest_verification_failures": len(bad_latest_results),
        "sqlite_integrity": integrity,
        "foreign_key_errors": foreign_key_errors,
        "database_bytes": (root / "agentbridge.db").stat().st_size,
        "duration_seconds": round(duration, 3),
        "cycles_per_second": round(cycles / duration, 3),
        "concurrency": concurrency,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bounded SZ-AgentBridge soak checks."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--cycles", type=int, default=500)
    parser.add_argument("--restart-every", type=int, default=25)
    parser.add_argument("--fault-every", type=int, default=17)
    parser.add_argument("--repair-every", type=int, default=19)
    parser.add_argument("--concurrent-tasks", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root or Path("data/long-run") / uuid4().hex
    try:
        report = run_validation(
            root=root,
            cycles=args.cycles,
            restart_every=args.restart_every,
            fault_every=args.fault_every,
            repair_every=args.repair_every,
            concurrent_tasks=args.concurrent_tasks,
            workers=args.workers,
        )
    except Exception as exc:  # noqa: BLE001 - top-level report boundary
        report = {
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    report_path = root / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report={report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
