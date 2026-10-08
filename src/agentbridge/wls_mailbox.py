"""A thin file-protocol adapter between SZ-AgentBridge and WLS AgenticHarness.

WLS remains the sole graph/lease owner. AgentBridge remains the sole executor
and verifier. No direct ChatGPT session access or new long-lived controller.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from agentbridge.domain.enums import AttemptStatus, TaskState, VerificationStatus
from agentbridge.domain.task import TaskEnvelope
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository


def _digest(data: object) -> str:
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise ValueError("invalid WLS mailbox message ID")
    return value


def read_wls_task(root: Path, message_id: str) -> dict[str, Any]:
    """Reject a damaged, misdirected, or substituted WLS task envelope."""
    safe = _safe_id(message_id)
    path = root.resolve() / "tasks" / f"{safe}.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128_000:
        raise ValueError("WLS task file is missing, symlinked, or oversized")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("WLS envelope must be an object")
    required = {
        "protocol_version", "message_id", "graph_id", "node_id", "lease_id",
        "sender", "recipient", "payload", "payload_digest",
    }
    if set(data) != required or data["protocol_version"] != "1.0":
        raise ValueError("unknown WLS task protocol")
    if data["message_id"] != safe or data["sender"] != "LivingSystem.AgenticHarness":
        raise ValueError("WLS message identity does not match")
    if data["recipient"] != "agentbridge":
        raise ValueError("WLS task is not addressed to AgentBridge")
    if any(not isinstance(data[k], str) or not data[k] for k in ("graph_id", "node_id", "lease_id")):
        raise ValueError("missing graph/lease identity")
    payload = data["payload"]
    if not isinstance(payload, dict) or data["payload_digest"] != _digest(payload):
        raise ValueError("WLS task digest mismatch")
    expected = _digest({
        "graph_id": data["graph_id"], "node_id": data["node_id"],
        "lease_id": data["lease_id"], "authority": "LivingSystem.AgenticHarness",
    })
    if payload.get("lease_fencing_token") != expected:
        raise ValueError("WLS lease fencing token does not match")
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        raise ValueError("WLS node title is missing")
    return data


def _task_id(wls: dict[str, Any]) -> str:
    return "WLS-" + _digest({
        "message_id": wls["message_id"], "lease_id": wls["lease_id"],
    })[:20].upper()


def prepare_wls_task(
    *, mailbox_root: Path, message_id: str, workspace: Path,
    output: Path, check_file: str, executor: str = "fake",
) -> dict[str, str]:
    """Prepare an AgentBridge task without executing it or relaxing WLS controls."""
    wls = read_wls_task(mailbox_root, message_id)
    if executor not in {"fake", "opencode"}:
        raise ValueError("unsupported AgentBridge executor")
    directory = workspace.expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("workspace does not exist")
    if (
        not check_file or "\\" in check_file
        or Path(check_file).is_absolute()
        or any(part in {"", ".", ".."} for part in check_file.split("/"))
    ):
        raise ValueError("acceptance file must be a safe relative path")
    result_path = (directory / check_file).resolve()
    if directory not in result_path.parents:
        raise ValueError("acceptance file escapes workspace")
    if executor == "opencode" and result_path.exists():
        raise ValueError("acceptance file already exists; choose a fresh output to prove work")
    title = str(wls["payload"]["title"])
    # OpenCode's edit/shell permission categories are inseparable, hence
    # explicit allow grants within the pre-existing AgentBridge worker policy.
    access = "allow" if executor == "opencode" else "deny"
    task = TaskEnvelope.model_validate({
        "schema_version": "1.0",
        "task_id": _task_id(wls),
        "title": title,
        "type": "engineering",
        "goal": title,
        "source": {
            "adapter": "wls_mailbox",
            "conversation_ref": wls["message_id"],
        },
        "target": {
            "executor_id": executor,
            "workspace": str(directory),
            "capabilities_required": ["filesystem", "shell"],
        },
        "scope": {"include": ["."], "exclude": []},
        "constraints": [
            "Candidate only; do not merge, push, deploy, or read credentials.",
            "WLS controls final acceptance and lease completion.",
        ],
        "acceptance": [{
            "id": "WLS_FILE_1", "type": "fileexists", "path": check_file,
        }],
        "permissions": {
            "file_write": {"mode": access},
            "delete": {"mode": access},
            "network": {"mode": access},
            "shell": {"mode": access},
        },
        "budget": {
            "max_executor_rounds": 1, "max_retries_per_node": 0,
            "timeout_seconds": 300,
        },
        "stop": {
            "success": "The declared acceptance file exists in the workspace.",
            "blocked": "The worker or requested permission is unavailable.",
            "no_progress": "No independently checked file exists.",
        },
    })
    out = output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    if out.exists():
        saved = json.loads(out.read_text(encoding="utf-8"))
        incoming = task.model_dump(mode="json")
        # Source.created_at is the only nondeterministic default. A retry
        # must be idempotent while all authority, scope and permissions stay
        # byte-for-byte equivalent after canonical JSON normalization.
        if isinstance(saved, dict):
            saved.get("source", {}).pop("created_at", None)
        incoming["source"].pop("created_at", None)
        if saved != incoming:
            raise FileExistsError("existing task envelope has different content")
    else:
        stage = out.with_suffix(out.suffix + ".tmp")
        stage.write_text(encoded, encoding="utf-8")
        os.replace(stage, out)
    return {"task_id": task.task_id, "task_file": str(out), "wls_message_id": message_id}


def reply_to_wls(
    *, mailbox_root: Path, message_id: str, db_path: Path,
) -> dict[str, str]:
    """Produce a fenced WLS mailbox result from persisted, verified facts."""
    wls = read_wls_task(mailbox_root, message_id)
    task_id = _task_id(wls)
    db = Database(db_path)
    db.initialize()
    with db.connect() as conn:
        repo = AgentRepository(conn)
        envelope = repo.get_envelope(task_id)
        runtime = repo.get_runtime(task_id)
        checks = repo.latest_verification_results(runtime.run_id)
        attempt = repo.latest_attempt(runtime.run_id)
    if envelope.source.adapter != "wls_mailbox" or envelope.source.conversation_ref != message_id:
        raise ValueError("task is not bound to the original WLS message")
    if runtime.state not in {
        TaskState.COMPLETED, TaskState.BLOCKED, TaskState.RECOVERY_REQUIRED,
        TaskState.REPAIR_READY, TaskState.ACCEPTANCE_FAILED,
    }:
        raise ValueError("AgentBridge task is not resolved; no reply issued")
    # A fake subprocess passing file-exists checks is NOT a completed WLS
    # execution. Bind success to the declared real executor and its actual
    # finished attempt, not to a verifier that may inspect pre-existing files.
    passed = (
        runtime.state == TaskState.COMPLETED
        and envelope.target.executor_id == "opencode"
        and runtime.executor_id == "opencode"
        and attempt is not None
        and attempt.executor_id == "opencode"
        and attempt.status == AttemptStatus.FINISHED
        and attempt.exit_code == 0
        and bool(checks)
        and all(check.status == VerificationStatus.PASS for check in checks)
    )
    status = "SUCCEEDED" if passed else "FAILED"
    result_payload: dict[str, Any] = {
        "agentbridge_task_id": task_id,
        "agentbridge_run_id": runtime.run_id,
        "agentbridge_attempt_id": attempt.attempt_id if attempt else None,
        "agentbridge_state": runtime.state.value,
        "verified_checks": [{
            "check_id": c.check_id, "status": c.status.value,
            "verifier_id": c.verifier_id,
        } for c in checks],
        "checked_scope": "agentbridge_declared_acceptance_only",
        "lease_fencing_token": wls["payload"]["lease_fencing_token"],
    }
    if not passed:
        result_payload["error"] = (
            "AgentBridge has not produced a completed real OpenCode attempt "
            "with independently passing acceptance results"
        )
    reply_id = "ab-" + _digest({
        "wls_message_id": message_id, "run_id": runtime.run_id,
    })[:24]
    reply: dict[str, Any] = {
        "protocol_version": "1.0",
        "message_id": reply_id,
        "in_reply_to": message_id,
        "graph_id": wls["graph_id"],
        "node_id": wls["node_id"],
        "lease_id": wls["lease_id"],
        "sender": "SZ-AgentBridge",
        "recipient": "LivingSystem.AgenticHarness",
        "status": status,
        "payload": result_payload,
        "payload_digest": _digest(result_payload),
    }
    directory = mailbox_root.resolve() / "results"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{reply_id}.json"
    serialized = json.dumps(reply, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != reply:
            raise FileExistsError("WLS reply ID collision")
    else:
        stage = target.with_suffix(".json.tmp")
        stage.write_text(serialized, encoding="utf-8")
        os.replace(stage, target)
    return {
        "message_id": reply_id, "in_reply_to": message_id,
        "status": status, "path": str(target), "task_id": task_id,
    }
