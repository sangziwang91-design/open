import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from agentbridge.bridge.protocol import (
    BrainTaskMessage,
    BridgeJobView,
    BridgeResultMessage,
)
from agentbridge.persistence.database import Database


class BridgeRequestConflictError(ValueError):
    """A request id was reused with different content."""


BridgeJobStatus = Literal["QUEUED", "RUNNING", "FINISHED", "ERROR"]


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class StoredBridgeJob:
    job_id: str
    task: BrainTaskMessage
    status: BridgeJobStatus
    task_id: str | None
    run_id: str | None
    result: BridgeResultMessage | None
    error: str | None
    created_at: str
    updated_at: str

    def view(self) -> BridgeJobView:
        return BridgeJobView(
            job_id=self.job_id,
            session_id=self.task.session_id,
            request_id=self.task.request_id,
            status=self.status,
            task_id=self.task_id,
            run_id=self.run_id,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class BridgeStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredBridgeJob:
        result = (
            BridgeResultMessage.model_validate_json(row["result_json"])
            if row["result_json"]
            else None
        )
        return StoredBridgeJob(
            job_id=row["job_id"],
            task=BrainTaskMessage.model_validate_json(row["request_json"]),
            status=cast(BridgeJobStatus, row["status"]),
            task_id=row["task_id"],
            run_id=row["run_id"],
            result=result,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, job_id: str) -> StoredBridgeJob | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bridge_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_by_request(
        self, session_id: str, request_id: str
    ) -> StoredBridgeJob | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT * FROM bridge_jobs
                   WHERE session_id=? AND request_id=?""",
                (session_id, request_id),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def create_or_get(self, task: BrainTaskMessage) -> tuple[StoredBridgeJob, bool]:
        now = utc_iso()
        job_id = f"JOB-{uuid4().hex[:12].upper()}"
        request_json = task.canonical_json()
        request_hash = task.request_hash()
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO bridge_sessions(
                       session_id, last_request_id, created_at, updated_at
                   ) VALUES (?, NULL, ?, ?)""",
                (task.session_id, now, now),
            )
            try:
                conn.execute(
                    """INSERT INTO bridge_jobs(
                           job_id, session_id, request_id, request_hash, request_json,
                           status, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, 'QUEUED', ?, ?)""",
                    (
                        job_id,
                        task.session_id,
                        task.request_id,
                        request_hash,
                        request_json,
                        now,
                        now,
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                created = False
            row = conn.execute(
                """SELECT * FROM bridge_jobs
                   WHERE session_id=? AND request_id=?""",
                (task.session_id, task.request_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("bridge job insert did not persist")
            if row["request_hash"] != request_hash:
                raise BridgeRequestConflictError(
                    "request_id was already used with different content"
                )
            if created:
                conn.execute(
                    """UPDATE bridge_sessions
                       SET last_request_id=?, updated_at=? WHERE session_id=?""",
                    (task.request_id, now, task.session_id),
                )
        return self._from_row(row), created

    def active_count(self) -> int:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS count FROM bridge_jobs
                   WHERE status IN ('QUEUED', 'RUNNING')"""
            ).fetchone()
        return int(row["count"])

    def queued(self) -> list[StoredBridgeJob]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM bridge_jobs WHERE status='QUEUED'
                   ORDER BY created_at, job_id"""
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def running(self) -> list[StoredBridgeJob]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM bridge_jobs WHERE status='RUNNING'
                   ORDER BY created_at, job_id"""
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def claim(self, job_id: str) -> StoredBridgeJob | None:
        now = utc_iso()
        with self.database.connect() as conn:
            cursor = conn.execute(
                """UPDATE bridge_jobs SET status='RUNNING', updated_at=?
                   WHERE job_id=? AND status='QUEUED'""",
                (now, job_id),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM bridge_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("claimed bridge job disappeared")
        return self._from_row(row)

    def bind_run(self, job_id: str, task_id: str, run_id: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE bridge_jobs SET task_id=?, run_id=?, updated_at=?
                   WHERE job_id=? AND status='RUNNING'""",
                (task_id, run_id, utc_iso(), job_id),
            )

    def finish(self, job_id: str, result: BridgeResultMessage) -> None:
        with self.database.connect() as conn:
            cursor = conn.execute(
                """UPDATE bridge_jobs
                   SET status='FINISHED', task_id=?, run_id=?, result_json=?,
                       error=NULL, updated_at=?
                   WHERE job_id=? AND status='RUNNING'""",
                (
                    result.task_id,
                    result.run_id,
                    result.model_dump_json(),
                    utc_iso(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("bridge job could not be finalized")

    def fail(self, job_id: str, result: BridgeResultMessage, error: str) -> None:
        with self.database.connect() as conn:
            cursor = conn.execute(
                """UPDATE bridge_jobs
                   SET status='ERROR', task_id=?, run_id=?, result_json=?, error=?,
                       updated_at=? WHERE job_id=? AND status='RUNNING'""",
                (
                    result.task_id,
                    result.run_id,
                    result.model_dump_json(),
                    error[:1000],
                    utc_iso(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("bridge job error could not be finalized")

    def recover_interrupted(self) -> int:
        """Fail closed after controller loss; never replay an unknown process."""
        recovered = 0
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bridge_jobs WHERE status='RUNNING'"
            ).fetchall()
            for row in rows:
                result = BridgeResultMessage(
                    session_id=row["session_id"],
                    request_id=row["request_id"],
                    job_id=row["job_id"],
                    task_id=row["task_id"],
                    run_id=row["run_id"],
                    status="BLOCKED",
                    state="RECOVERY_REQUIRED",
                    summary="The local controller stopped during execution; no blind replay was attempted.",
                    next_action="INPUT",
                    requires_human_decision=True,
                    question_to_human=(
                        "Confirm the prior process is no longer authoritative, then submit a new request id."
                    ),
                    error="controller_interrupted",
                )
                conn.execute(
                    """UPDATE bridge_jobs SET status='ERROR', result_json=?, error=?,
                       updated_at=? WHERE job_id=? AND status='RUNNING'""",
                    (
                        result.model_dump_json(),
                        "controller_interrupted",
                        utc_iso(),
                        row["job_id"],
                    ),
                )
                recovered += 1
        return recovered
