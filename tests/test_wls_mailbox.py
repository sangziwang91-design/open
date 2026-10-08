"""WLS -> AgentBridge -> verified WLS result contract regression."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentbridge.cli import app
from agentbridge.wls_mailbox import (
    _digest,
    _task_id,
    prepare_wls_task,
    read_wls_task,
    reply_to_wls,
)

runner = CliRunner()


@pytest.fixture
def wls_task(tmp_path: Path):
    mailbox = tmp_path / "mailbox"
    (mailbox / "tasks").mkdir(parents=True)
    p = {
        "title": "Produce bounded candidate output",
        "role": "coding",
        "acceptance": ["candidate output exists"],
        "risk": "REVERSIBLE_WRITE",
        "conflict_domain": "demo",
        "worker_id": "bridge-worker",
        "lease_fencing_token": _digest({
            "graph_id": "graph-1",
            "node_id": "node-1",
            "lease_id": "lease-1",
            "authority": "LivingSystem.AgenticHarness",
        }),
    }
    task = {
        "protocol_version": "1.0",
        "message_id": "msg-A1",
        "graph_id": "graph-1",
        "node_id": "node-1",
        "lease_id": "lease-1",
        "sender": "LivingSystem.AgenticHarness",
        "recipient": "agentbridge",
        "payload": p,
        "payload_digest": _digest(p),
    }
    path = mailbox / "tasks" / "msg-A1.json"
    path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    return mailbox, task, path


def test_real_cli_wls_task_roundtrip_with_checked_acceptance(
    tmp_path: Path, wls_task,
):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Fake executor cannot generate software; an independently present file
    # makes the file-existence acceptance check meaningful for transport.
    (workspace / "approved.txt").write_text("verified", encoding="utf-8")
    contract = tmp_path / "to-agentbridge.json"
    db = tmp_path / "bridge.db"
    runs = tmp_path / "runs"
    prepare = runner.invoke(app, [
        "wls-prepare", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--output", str(contract),
        "--check-file", "approved.txt", "--executor", "fake",
    ])
    assert prepare.exit_code == 0, prepare.output
    parsed = json.loads(contract.read_text(encoding="utf-8"))
    assert parsed["source"]["adapter"] == "wls_mailbox"
    assert parsed["source"]["conversation_ref"] == "msg-A1"
    task_id = parsed["task_id"]
    assert task_id == _task_id(task)
    assert runner.invoke(app, ["submit", str(contract), "--db", str(db)]).exit_code == 0
    # A submitted but unverified AgentBridge task must not claim completion.
    with pytest.raises(ValueError, match="not resolved"):
        reply_to_wls(mailbox_root=mailbox, message_id="msg-A1", db_path=db)
    running = runner.invoke(app, [
        "run", task_id, "--executor", "fake", "--db", str(db),
        "--runs-dir", str(runs),
    ])
    assert running.exit_code == 0, running.output
    checked = runner.invoke(app, [
        "verify", task_id, "--db", str(db), "--runs-dir", str(runs),
    ])
    assert checked.exit_code == 0, checked.output
    sent = runner.invoke(app, [
        "wls-reply", "msg-A1", "--mailbox-root", str(mailbox),
        "--db", str(db),
    ])
    assert sent.exit_code == 0, sent.output
    replies = list((mailbox / "results").glob("*.json"))
    assert len(replies) == 1
    result = json.loads(replies[0].read_text(encoding="utf-8"))
    assert result["status"] == "SUCCEEDED"
    assert result["in_reply_to"] == task["message_id"]
    assert result["lease_id"] == task["lease_id"]
    assert result["payload"]["lease_fencing_token"] == task["payload"]["lease_fencing_token"]
    assert result["payload"]["verified_checks"][0]["status"] == "PASS"
    assert result["payload_digest"] == _digest(result["payload"])
    assert result["recipient"] == "LivingSystem.AgenticHarness"
    # Result serialization is replay-safe; same run won't invent another reply.
    assert reply_to_wls(mailbox_root=mailbox, message_id="msg-A1", db_path=db)["status"] == "SUCCEEDED"
    assert len(list((mailbox / "results").glob("*.json"))) == 1


@pytest.mark.parametrize("field,change,match", [
    ("payload_digest", "0" * 64, "digest"),
    ("recipient", "not-me", "addressed"),
    ("message_id", "other", "identity"),
    ("protocol_version", "0", "protocol"),
])
def test_reject_modified_wls_task(wls_task, field, change, match):
    mailbox, task, path = wls_task
    task[field] = change
    path.write_text(json.dumps(task), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        read_wls_task(mailbox, "msg-A1")


def test_reject_bad_lease_fencing(wls_task):
    mailbox, task, path = wls_task
    task["payload"]["lease_fencing_token"] = "bad"
    task["payload_digest"] = _digest(task["payload"])
    path.write_text(json.dumps(task), encoding="utf-8")
    with pytest.raises(ValueError, match="fencing"):
        read_wls_task(mailbox, "msg-A1")


@pytest.mark.parametrize("path", ["../secrets", "/tmp/secrets", "dir/../../private", "a\\b"])
def test_refuse_unsafe_acceptance_paths(tmp_path, wls_task, path):
    mailbox, task, _ = wls_task
    with pytest.raises(ValueError, match="acceptance"):
        prepare_wls_task(
            mailbox_root=mailbox, message_id=task["message_id"],
            workspace=tmp_path, output=tmp_path / "task.json",
            check_file=path,
        )


def test_prepare_does_not_start_model_or_executor(tmp_path, wls_task):
    mailbox, task, _ = wls_task
    output = tmp_path / "task.json"
    prepared = prepare_wls_task(
        mailbox_root=mailbox, message_id=task["message_id"],
        workspace=tmp_path, output=output, check_file="safe.txt",
    )
    assert output.is_file()
    assert prepared["task_id"].startswith("WLS-")
    assert not (tmp_path / "bridge.db").exists()
    assert prepare_wls_task(
        mailbox_root=mailbox, message_id=task["message_id"],
        workspace=tmp_path, output=output, check_file="safe.txt",
    ) == prepared
