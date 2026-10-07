from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.owner_acceptance import prepare, verify


def make_bridge_db(path: Path, nonce: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """CREATE TABLE bridge_jobs(
                   job_id TEXT, task_id TEXT, run_id TEXT, status TEXT,
                   request_json TEXT, result_json TEXT, created_at TEXT,
                   updated_at TEXT, error TEXT
               )"""
        )
        result = {
            "status": "COMPLETED",
            "next_action": "CLOSE",
            "requires_human_decision": False,
            "error": None,
            "checks": [
                {"check_id": "file", "status": "PASS", "detail": "exists"},
                {"check_id": "content", "status": "PASS", "detail": "exact"},
            ],
        }
        connection.execute(
            """INSERT INTO bridge_jobs VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "JOB-OWNER",
                "TASK-OWNER",
                "RUN-OWNER",
                "FINISHED",
                json.dumps({"goal": f"owner acceptance {nonce}"}),
                json.dumps(result),
                "2026-10-07T00:00:00+00:00",
                "2026-10-07T00:01:00+00:00",
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_owner_acceptance_prepare_and_verify(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_path = tmp_path / "state.json"
    prepared = prepare(workspace, state_path)

    nonce = str(prepared["nonce"])
    result_file = workspace / "agentbridge-owner-acceptance-result.txt"
    result_file.write_text(f"AGENTBRIDGE_OWNER_ACCEPTANCE={nonce}\n", encoding="utf-8")
    database = tmp_path / "bridge.db"
    make_bridge_db(database, nonce)

    receipt = verify(
        workspace,
        database,
        state_path,
        tmp_path / "receipt.json",
    )

    assert receipt["passed"] is True
    assert receipt["bridge"]["matched"] is True
    assert receipt["bridge"]["all_checks_pass"] is True
    assert receipt["workspace_name"] == "workspace"
    serialized = json.dumps(receipt)
    assert str(workspace.resolve()) not in serialized
    assert nonce not in serialized


def test_owner_acceptance_rejects_unverified_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_path = tmp_path / "state.json"
    prepared = prepare(workspace, state_path)
    nonce = str(prepared["nonce"])
    (workspace / "agentbridge-owner-acceptance-result.txt").write_text(
        "wrong", encoding="utf-8"
    )
    database = tmp_path / "bridge.db"
    make_bridge_db(database, nonce)

    receipt = verify(workspace, database, state_path, tmp_path / "receipt.json")

    assert receipt["passed"] is False
