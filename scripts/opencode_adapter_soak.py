import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentbridge.domain.enums import AttemptStatus, TaskState
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.executors.opencode import OpenCodeExecutor
from agentbridge.interpreters.artifact_collector import hash_file
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.execution_service import ExecutionService
from agentbridge.services.state_manager import StateManager
from agentbridge.services.verification_service import VerificationService

SHIM_SOURCE = f"""#!{sys.executable}
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if "--version" in sys.argv:
    print("1.18.11")
    raise SystemExit(0)
if "--help" in sys.argv:
    print("--format --dir --agent --title")
    raise SystemExit(0)

title = sys.argv[sys.argv.index("--title") + 1]
try:
    index = int(title.rsplit("-", 1)[-1])
except ValueError:
    index = 0
fault_every = int(os.environ.get("AGENTBRIDGE_SOAK_FAULT_EVERY", "0"))
timeout_every = int(os.environ.get("AGENTBRIDGE_SOAK_TIMEOUT_EVERY", "0"))
marker_root = Path(os.environ["AGENTBRIDGE_SOAK_MARKER_ROOT"])
marker_root.mkdir(parents=True, exist_ok=True)

timeout_marker = marker_root / f"timeout-{{index}}"
if timeout_every and index % timeout_every == 0 and not timeout_marker.exists():
    timeout_marker.write_text("injected", encoding="utf-8")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    (marker_root / f"child-{{index}}.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)

fault_marker = marker_root / f"fault-{{index}}"
if (
    fault_every
    and index % fault_every == 0
    and not (timeout_every and index % timeout_every == 0)
    and not fault_marker.exists()
):
    fault_marker.write_text("injected", encoding="utf-8")
    print("injected executor failure", file=sys.stderr)
    raise SystemExit(9)

result_names = re.findall(r"[A-Za-z0-9._-]+\\.txt", sys.argv[-1])
if not result_names:
    raise SystemExit("goal did not name a .txt result")
result = Path(result_names[0])
result.write_text("opencode adapter subprocess completed\\n", encoding="utf-8")
print('{{"type":"text","text":"adapter soak completed"}}')
"""


def make_task(index: int, workspace: Path) -> TaskEnvelope:
    return TaskEnvelope.model_validate(
        {
            "task_id": f"TASK-ADAPTER-{index:06d}",
            "title": f"OpenCode adapter cycle {index}",
            "type": "validation",
            "goal": f"create result-{index:06d}.txt",
            "source": {"adapter": "opencode-adapter-soak"},
            "target": {
                "executor_id": "opencode",
                "workspace": str(workspace),
            },
            "scope": {"include": ["."], "exclude": []},
            "acceptance": [
                {
                    "id": "A1",
                    "type": "fileexists",
                    "path": f"result-{index:06d}.txt",
                }
            ],
            "permissions": {
                "file_write": {"mode": "allow"},
                "delete": {"mode": "allow"},
                "network": {"mode": "allow"},
                "shell": {"mode": "allow"},
            },
            "budget": {
                "max_executor_rounds": 2,
                "max_retries_per_node": 1,
                "timeout_seconds": 1,
            },
            "stop": {"success": "accepted", "blocked": "record blocker"},
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
        manager.transition(runtime, TaskState.VALIDATING, "ValidationStarted", "soak")
        manager.transition(runtime, TaskState.READY, "TaskReady", "soak")
    return runtime


def recover(database: Database, runtime: TaskRuntime) -> None:
    with UnitOfWork(database) as uow:
        StateManager(AgentRepository(uow.connection)).transition(
            runtime, TaskState.READY, "RecoveryAccepted", "soak_retry"
        )


def reload_task(database: Database, task_id: str) -> tuple[TaskEnvelope, TaskRuntime]:
    with database.connect() as conn:
        repo = AgentRepository(conn)
        return repo.get_envelope(task_id), repo.get_runtime(task_id)


def process_is_active(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_stays_active(pid: int, settle_seconds: float = 2.0) -> bool:
    """Allow SIGKILL delivery/re-parenting to settle before flagging a leak."""
    deadline = time.monotonic() + settle_seconds
    while time.monotonic() < deadline:
        if not process_is_active(pid):
            return False
        time.sleep(0.02)
    return process_is_active(pid)


def run_validation(
    root: Path,
    cycles: int = 100,
    fault_every: int = 17,
    timeout_every: int = 29,
    restart_every: int = 20,
) -> dict[str, object]:
    if cycles < 1:
        raise ValueError("cycles must be positive")
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir()
    markers = root / "markers"
    if os.name == "nt":
        shim_script = root / "opencode-shim.py"
        shim_script.write_text(SHIM_SOURCE, encoding="utf-8")
        shim = root / "opencode-shim.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{shim_script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        shim = root / "opencode-shim"
        shim.write_text(SHIM_SOURCE, encoding="utf-8")
        shim.chmod(0o755)
    database_path = root / "agentbridge.db"
    database = Database(database_path)
    database.initialize()
    runs_dir = root / "runs"

    variables = {
        "AGENTBRIDGE_SOAK_FAULT_EVERY": str(fault_every),
        "AGENTBRIDGE_SOAK_TIMEOUT_EVERY": str(timeout_every),
        "AGENTBRIDGE_SOAK_MARKER_ROOT": str(markers),
    }
    previous = {name: os.environ.get(name) for name in variables}
    os.environ.update(variables)
    started = time.monotonic()
    fault_cycles = 0
    timeout_cycles = 0
    try:
        for index in range(1, cycles + 1):
            task = make_task(index, workspace)
            runtime = submit_ready(database, task)
            if restart_every > 0 and index % restart_every == 0:
                database = Database(database_path)
                database.initialize()
                task, runtime = reload_task(database, task.task_id)

            should_timeout = timeout_every > 0 and index % timeout_every == 0
            should_fault = (
                fault_every > 0 and index % fault_every == 0 and not should_timeout
            )
            execution = ExecutionService(database, runs_dir)
            ok = execution.run(runtime, task, OpenCodeExecutor(str(shim)))
            if should_timeout or should_fault:
                if ok or runtime.state != TaskState.RECOVERY_REQUIRED:
                    raise AssertionError(
                        "Injected adapter failure did not require recovery"
                    )
                timeout_cycles += int(should_timeout)
                fault_cycles += int(should_fault)
                recover(database, runtime)
                ok = ExecutionService(database, runs_dir).run(
                    runtime, task, OpenCodeExecutor(str(shim))
                )
            if not ok:
                raise AssertionError(f"Adapter cycle {index} did not execute")
            passed, _, _ = VerificationService(database, runs_dir).verify(runtime, task)
            if not passed or runtime.state != TaskState.COMPLETED:
                raise AssertionError(f"Adapter cycle {index} did not complete")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    bad_artifacts: list[str] = []
    bad_policy_events: list[str] = []
    with database.connect() as conn:
        repo = AgentRepository(conn)
        runs = conn.execute("SELECT run_id, task_id, state FROM runs").fetchall()
        artifact_rows = conn.execute(
            "SELECT artifact_id, path, sha256 FROM artifacts"
        ).fetchall()
        for artifact in artifact_rows:
            path = Path(artifact["path"])
            if not path.is_file() or hash_file(path) != artifact["sha256"]:
                bad_artifacts.append(artifact["artifact_id"])
        for row in runs:
            events = repo.list_events(row["task_id"])
            prepared = [
                event for event in events if event.event_type == "ExecutorPrepared"
            ]
            if not prepared or any(
                "policy_hash" not in event.payload
                or "opencode_version" not in event.payload
                for event in prepared
            ):
                bad_policy_events.append(row["task_id"])
        attempts = conn.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
        unfinished_attempts = conn.execute(
            "SELECT COUNT(*) FROM execution_attempts "
            "WHERE status IN ('CREATED', 'RUNNING')"
        ).fetchone()[0]
        timed_out_attempts = conn.execute(
            "SELECT COUNT(*) FROM execution_attempts WHERE status=?",
            (AttemptStatus.TIMED_OUT.value,),
        ).fetchone()[0]
        failed_attempts = conn.execute(
            "SELECT COUNT(*) FROM execution_attempts WHERE status=?",
            (AttemptStatus.FAILED.value,),
        ).fetchone()[0]
        completed = sum(row["state"] == TaskState.COMPLETED.value for row in runs)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    active_children = []
    if os.name == "posix" and markers.exists():
        for path in markers.glob("child-*.pid"):
            pid = int(path.read_text(encoding="utf-8"))
            if process_stays_active(pid):
                active_children.append(pid)

    expected_attempts = cycles + fault_cycles + timeout_cycles
    if completed != cycles or attempts != expected_attempts:
        raise AssertionError("Adapter completion or attempt counts are inconsistent")
    if unfinished_attempts or bad_artifacts or bad_policy_events or active_children:
        raise AssertionError(
            "Adapter soak invariants failed: "
            f"unfinished_attempts={unfinished_attempts}, "
            f"bad_artifacts={bad_artifacts}, "
            f"bad_policy_events={bad_policy_events}, "
            f"active_children={active_children}"
        )
    if timed_out_attempts != timeout_cycles or failed_attempts != fault_cycles:
        raise AssertionError("Injected failure status counts are inconsistent")
    if integrity != "ok" or foreign_key_errors:
        raise AssertionError("Adapter soak database integrity failed")

    duration = time.monotonic() - started
    return {
        "status": "PASS",
        "cycles": cycles,
        "attempts": attempts,
        "fault_cycles": fault_cycles,
        "timeout_cycles": timeout_cycles,
        "restarts": cycles // restart_every if restart_every > 0 else 0,
        "artifacts": len(artifact_rows),
        "artifact_integrity_failures": len(bad_artifacts),
        "policy_event_failures": len(bad_policy_events),
        "unfinished_attempts": unfinished_attempts,
        "active_child_processes": len(active_children),
        "sqlite_integrity": integrity,
        "foreign_key_errors": foreign_key_errors,
        "duration_seconds": round(duration, 3),
        "cycles_per_second": round(cycles / duration, 3),
        "opencode_contract_version": "1.18.11",
        "executor": "controlled-real-subprocess-shim",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Soak the OpenCode adapter through real OS subprocess boundaries."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--fault-every", type=int, default=17)
    parser.add_argument("--timeout-every", type=int, default=29)
    parser.add_argument("--restart-every", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix="agentbridge-opencode-soak-"))
    if args.root is None:
        root.rmdir()
    report = run_validation(
        root=root,
        cycles=args.cycles,
        fault_every=args.fault_every,
        timeout_every=args.timeout_every,
        restart_every=args.restart_every,
    )
    report["root"] = str(root)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
