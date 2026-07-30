import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT NOT NULL,
    task_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    envelope_yaml TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, task_version)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    task_version INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    latest_event_id TEXT,
    executor_id TEXT,
    workspace TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id, task_version) REFERENCES tasks(task_id, task_version)
);
CREATE TABLE IF NOT EXISTS events (
    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS execution_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    executor_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    signal TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS verification_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    status TEXT NOT NULL,
    verifier_id TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    failure_category TEXT,
    artifact_id TEXT,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS capability_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    environment_json TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = "agentbridge.db") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(verification_results)")
            }
            if "batch_id" not in columns:
                conn.execute(
                    "ALTER TABLE verification_results ADD COLUMN batch_id TEXT"
                )
                conn.execute(
                    """UPDATE verification_results
                       SET batch_id='legacy-' || run_id || '-' || created_at
                       WHERE batch_id IS NULL"""
                )
            run_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(runs)")
            }
            if "revision" not in run_columns:
                conn.execute(
                    "ALTER TABLE runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute("PRAGMA journal_mode = WAL")
