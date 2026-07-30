import json
import sqlite3
from datetime import datetime, timezone

import yaml

from agentbridge.domain.artifact import Artifact
from agentbridge.domain.capability import CapabilitySnapshot
from agentbridge.domain.enums import AttemptStatus, FailureCategory, TaskState, VerificationStatus
from agentbridge.domain.event import AgentEvent
from agentbridge.domain.execution_attempt import ExecutionAttempt
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.domain.verification import VerificationResult
from agentbridge.errors import TaskNotFoundError


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_task(self, envelope: TaskEnvelope, runtime: TaskRuntime) -> None:
        envelope_dict = envelope.model_dump(mode="json", by_alias=False)
        self.conn.execute(
            """INSERT INTO tasks(task_id, task_version, title, goal, envelope_yaml, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                envelope.task_id,
                runtime.task_version,
                envelope.title,
                envelope.goal,
                yaml.safe_dump(envelope_dict, sort_keys=False, allow_unicode=True),
                runtime.created_at.isoformat(),
            ),
        )
        self.conn.execute(
            """INSERT INTO runs(run_id, task_id, task_version, state, created_at, updated_at,
               latest_event_id, executor_id, workspace, attempt_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                runtime.run_id,
                runtime.task_id,
                runtime.task_version,
                runtime.state.value,
                runtime.created_at.isoformat(),
                runtime.updated_at.isoformat(),
                runtime.latest_event_id,
                runtime.executor_id,
                runtime.workspace,
                runtime.attempt_count,
            ),
        )

    def get_envelope(self, task_id: str, task_version: int | None = None) -> TaskEnvelope:
        if task_version is None:
            row = self.conn.execute(
                "SELECT envelope_yaml FROM tasks WHERE task_id=? ORDER BY task_version DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT envelope_yaml FROM tasks WHERE task_id=? AND task_version=?",
                (task_id, task_version),
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return TaskEnvelope.model_validate(yaml.safe_load(row["envelope_yaml"]))

    def get_runtime(self, task_id: str) -> TaskRuntime:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self._runtime_from_row(row)

    def get_runtime_by_run(self, run_id: str) -> TaskRuntime:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Run not found: {run_id}")
        return self._runtime_from_row(row)

    @staticmethod
    def _runtime_from_row(row: sqlite3.Row) -> TaskRuntime:
        return TaskRuntime(
            task_id=row["task_id"],
            task_version=row["task_version"],
            run_id=row["run_id"],
            state=TaskState(row["state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            latest_event_id=row["latest_event_id"],
            executor_id=row["executor_id"],
            workspace=row["workspace"],
            attempt_count=row["attempt_count"],
        )

    def update_runtime(self, runtime: TaskRuntime) -> None:
        self.conn.execute(
            """UPDATE runs SET state=?, updated_at=?, latest_event_id=?, executor_id=?,
               workspace=?, attempt_count=? WHERE run_id=?""",
            (
                runtime.state.value,
                runtime.updated_at.isoformat(),
                runtime.latest_event_id,
                runtime.executor_id,
                runtime.workspace,
                runtime.attempt_count,
                runtime.run_id,
            ),
        )

    def append_event(self, event: AgentEvent) -> AgentEvent:
        cur = self.conn.execute(
            """INSERT INTO events(event_id, task_id, run_id, timestamp, event_type, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.task_id,
                event.run_id,
                event.timestamp.isoformat(),
                event.event_type,
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        return event.model_copy(update={"sequence_id": int(cur.lastrowid)})

    def list_events(self, task_id: str) -> list[AgentEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE task_id=? ORDER BY sequence_id", (task_id,)
        ).fetchall()
        return [
            AgentEvent(
                event_id=row["event_id"],
                task_id=row["task_id"],
                run_id=row["run_id"],
                sequence_id=row["sequence_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def save_artifacts(self, artifacts: list[Artifact]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO artifacts(artifact_id, task_id, run_id, type, path,
               sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    a.artifact_id,
                    a.task_id,
                    a.run_id,
                    a.type.value,
                    a.path,
                    a.sha256,
                    a.created_by,
                    a.created_at.isoformat(),
                )
                for a in artifacts
            ],
        )

    def list_artifacts(self, run_id: str) -> list[Artifact]:
        rows = self.conn.execute(
            "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [Artifact(**dict(row)) for row in rows]

    def save_attempt(self, attempt: ExecutionAttempt) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO execution_attempts(attempt_id, run_id, task_id,
               executor_id, started_at, finished_at, status, exit_code, signal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt.attempt_id,
                attempt.run_id,
                attempt.task_id,
                attempt.executor_id,
                attempt.started_at.isoformat(),
                attempt.finished_at.isoformat() if attempt.finished_at else None,
                attempt.status.value,
                attempt.exit_code,
                attempt.signal,
            ),
        )

    def latest_attempt(self, run_id: str) -> ExecutionAttempt | None:
        row = self.conn.execute(
            "SELECT * FROM execution_attempts WHERE run_id=? ORDER BY started_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["status"] = AttemptStatus(data["status"])
        return ExecutionAttempt(**data)

    def save_verification_results(self, run_id: str, results: list[VerificationResult]) -> None:
        batch_created_at = utc_iso()
        self.conn.executemany(
            """INSERT INTO verification_results(run_id, check_id, status, verifier_id,
               verifier_version, failure_category, artifact_id, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    r.check_id,
                    r.status.value,
                    r.verifier_id,
                    r.verifier_version,
                    r.failure_category.value if r.failure_category else None,
                    r.artifact_id,
                    r.detail,
                    batch_created_at,
                )
                for r in results
            ],
        )

    def latest_verification_results(self, run_id: str) -> list[VerificationResult]:
        rows = self.conn.execute(
            """SELECT * FROM verification_results WHERE run_id=? AND created_at=(
               SELECT MAX(created_at) FROM verification_results WHERE run_id=?) ORDER BY id""",
            (run_id, run_id),
        ).fetchall()
        results: list[VerificationResult] = []
        for row in rows:
            data = dict(row)
            data["status"] = VerificationStatus(data["status"])
            data["failure_category"] = (
                FailureCategory(data["failure_category"]) if data["failure_category"] else None
            )
            for key in ("id", "run_id", "created_at"):
                data.pop(key, None)
            results.append(VerificationResult(**data))
        return results

    def save_capability_snapshot(self, snapshot: CapabilitySnapshot) -> None:
        self.conn.execute(
            """INSERT INTO capability_snapshots(snapshot_id, environment_json, detected_at)
               VALUES (?, ?, ?)""",
            (
                snapshot.snapshot_id,
                json.dumps(snapshot.environment, sort_keys=True),
                snapshot.detected_at.isoformat(),
            ),
        )
