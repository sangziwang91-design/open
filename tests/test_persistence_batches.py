import sqlite3
from pathlib import Path

from agentbridge.domain.enums import VerificationStatus
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.verification import VerificationResult
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from tests.test_repository import sample_task


def test_initialize_migrates_legacy_verification_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE verification_results (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               run_id TEXT NOT NULL,
               check_id TEXT NOT NULL,
               status TEXT NOT NULL,
               verifier_id TEXT NOT NULL,
               verifier_version TEXT NOT NULL,
               failure_category TEXT,
               artifact_id TEXT,
               detail TEXT NOT NULL,
               created_at TEXT NOT NULL)"""
        )
        conn.execute(
            """INSERT INTO verification_results(
               run_id, check_id, status, verifier_id, verifier_version, detail, created_at
               ) VALUES ('R', 'A1', 'PASS', 'command', '1.0', 'ok', 'same')"""
        )
    Database(path).initialize()
    with sqlite3.connect(path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(verification_results)")
        }
        batch_id = conn.execute(
            "SELECT batch_id FROM verification_results WHERE run_id='R'"
        ).fetchone()[0]
    assert "batch_id" in columns
    assert batch_id == "legacy-R-same"


def test_latest_verification_batch_does_not_merge_equal_timestamps(
    database, monkeypatch
) -> None:
    task = sample_task()
    runtime = TaskRuntime(task_id=task.task_id)
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        repo = AgentRepository(uow.conn)
        repo.save_task(task, runtime)
        monkeypatch.setattr(
            "agentbridge.persistence.repository.utc_iso", lambda: "same-timestamp"
        )
        repo.save_verification_results(
            runtime.run_id,
            [
                VerificationResult(
                    check_id="A1",
                    status=VerificationStatus.FAIL,
                    verifier_id="command",
                )
            ],
        )
        repo.save_verification_results(
            runtime.run_id,
            [
                VerificationResult(
                    check_id="A2",
                    status=VerificationStatus.PASS,
                    verifier_id="command",
                )
            ],
        )
    with database.connect() as conn:
        latest = AgentRepository(conn).latest_verification_results(runtime.run_id)
    assert [result.check_id for result in latest] == ["A2"]
