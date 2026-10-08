from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentbridge.bridge.store import BridgeRequestConflictError, BridgeStore
from agentbridge.persistence.database import Database
from tests.test_bridge_protocol import browser_task


@pytest.fixture
def bridge_store(tmp_path: Path) -> BridgeStore:
    database = Database(tmp_path / "bridge.db")
    database.initialize()
    return BridgeStore(database)


def test_request_is_idempotent(bridge_store: BridgeStore) -> None:
    first, created = bridge_store.create_or_get(browser_task())
    second, created_again = bridge_store.create_or_get(browser_task())
    assert created
    assert not created_again
    assert first.job_id == second.job_id


def test_reused_request_id_with_different_content_conflicts(
    bridge_store: BridgeStore,
) -> None:
    bridge_store.create_or_get(browser_task())
    with pytest.raises(BridgeRequestConflictError):
        bridge_store.create_or_get(browser_task(goal="different"))


def test_concurrent_duplicate_submission_creates_one_job(
    bridge_store: BridgeStore,
) -> None:
    def submit(_: int) -> tuple[str, bool]:
        job, created = bridge_store.create_or_get(browser_task())
        return job.job_id, created

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(24)))
    assert len({job_id for job_id, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1


def test_interrupted_running_job_fails_closed(bridge_store: BridgeStore) -> None:
    job, _ = bridge_store.create_or_get(browser_task())
    assert bridge_store.claim(job.job_id) is not None
    assert bridge_store.recover_interrupted() == 1
    recovered = bridge_store.get(job.job_id)
    assert recovered is not None
    assert recovered.status == "ERROR"
    assert recovered.result is not None
    assert recovered.result.status == "BLOCKED"
    assert recovered.result.state == "RECOVERY_REQUIRED"
    assert recovered.result.requires_human_decision


def test_database_migration_preserves_existing_core_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "bridge.db")
    database.initialize()
    database.initialize()
    with database.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"tasks", "runs", "bridge_sessions", "bridge_jobs"} <= tables
