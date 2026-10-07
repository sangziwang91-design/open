from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


RESULT_FILE = "agentbridge-owner-acceptance-result.txt"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def prepare(workspace: Path, state_path: Path) -> dict[str, object]:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace_not_found:{workspace}")
    nonce = secrets.token_hex(16)
    expected = f"AGENTBRIDGE_OWNER_ACCEPTANCE={nonce}"
    state = {
        "schema_version": 1,
        "prepared_at": utc_now(),
        "nonce": nonce,
        "result_file": RESULT_FILE,
        "expected_sha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "workspace_name": workspace.name,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    state["task_prompt"] = (
        "After you have manually armed AgentBridge in this logged-in ChatGPT tab, "
        f"use AgentBridge to create {RESULT_FILE} in the already-selected local workspace. "
        f"The file must contain exactly this one line: {expected}. "
        "Use a file-exists acceptance check and a command acceptance check that verifies "
        "the exact file content. Do not change any other file. Close only after the local "
        "verification checks pass and the AgentBridge result has been written back here."
    )
    return state


def _matching_finished_job(database: Path, nonce: str) -> dict[str, object] | None:
    if not database.is_file():
        return None
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT job_id,task_id,run_id,status,request_json,result_json,
                      created_at,updated_at,error
               FROM bridge_jobs
               WHERE status='FINISHED'
               ORDER BY created_at DESC, job_id DESC"""
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        request_json = str(row["request_json"] or "")
        if nonce not in request_json:
            continue
        result = json.loads(row["result_json"]) if row["result_json"] else {}
        return {
            "job_id": row["job_id"],
            "task_id": row["task_id"],
            "run_id": row["run_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error": row["error"],
            "result": result,
        }
    return None


def verify(
    workspace: Path,
    database: Path,
    state_path: Path,
    receipt_path: Path,
) -> dict[str, object]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    nonce = str(state["nonce"])
    expected = f"AGENTBRIDGE_OWNER_ACCEPTANCE={nonce}"
    result_path = workspace.resolve() / str(state["result_file"])
    actual = result_path.read_text(encoding="utf-8").strip() if result_path.is_file() else ""
    file_ok = actual == expected
    file_sha = hashlib.sha256(actual.encode("utf-8")).hexdigest() if actual else None

    job = _matching_finished_job(database.resolve(), nonce)
    result = dict(job.get("result") or {}) if job else {}
    checks = result.get("checks") if isinstance(result.get("checks"), list) else []
    checks_pass = bool(checks) and all(
        isinstance(item, dict) and item.get("status") == "PASS" for item in checks
    )
    bridge_ok = bool(
        job
        and job.get("status") == "FINISHED"
        and result.get("status") == "COMPLETED"
        and result.get("next_action") == "CLOSE"
        and result.get("requires_human_decision") is False
        and not result.get("error")
        and checks_pass
    )

    passed = bool(
        file_ok
        and file_sha == state.get("expected_sha256")
        and bridge_ok
    )
    receipt = {
        "schema_version": 1,
        "checked_at": utc_now(),
        "passed": passed,
        "workspace_name": workspace.resolve().name,
        "result_file": str(state["result_file"]),
        "result_sha256": file_sha,
        "bridge": {
            "matched": bool(job),
            "job_id": job.get("job_id") if job else None,
            "task_id": job.get("task_id") if job else None,
            "run_id": job.get("run_id") if job else None,
            "status": job.get("status") if job else None,
            "result_status": result.get("status") if job else None,
            "next_action": result.get("next_action") if job else None,
            "check_count": len(checks),
            "all_checks_pass": checks_pass,
        },
        "claim_ceiling": (
            "one logged-in owner-host ChatGPT web -> AgentBridge -> local executor -> "
            "verification -> feedback acceptance only; not longitudinal reliability or "
            "support for future ChatGPT DOM revisions"
        ),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or verify one owner-host AgentBridge acceptance.")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare")
    prep.add_argument("--workspace", type=Path, required=True)
    prep.add_argument("--state", type=Path, default=Path(".agentbridge/owner-acceptance-state.json"))

    check = sub.add_parser("verify")
    check.add_argument("--workspace", type=Path, required=True)
    check.add_argument("--db", type=Path, default=Path(".agentbridge/bridge.db"))
    check.add_argument("--state", type=Path, default=Path(".agentbridge/owner-acceptance-state.json"))
    check.add_argument("--receipt", type=Path, default=Path(".agentbridge/owner-acceptance-receipt.json"))

    args = parser.parse_args()
    if args.command == "prepare":
        payload = prepare(args.workspace, args.state)
    else:
        payload = verify(args.workspace, args.db, args.state, args.receipt)
    print(json.dumps(payload, indent=2))
    return 0 if args.command == "prepare" or payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
