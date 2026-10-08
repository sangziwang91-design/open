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
from tests.test_opencode_executor import make_shim

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
    # Declared fake workers are never allowed to claim real WLS execution.
    assert result["status"] == "FAILED"
    assert result["in_reply_to"] == task["message_id"]
    assert result["lease_id"] == task["lease_id"]
    assert result["payload"]["lease_fencing_token"] == task["payload"]["lease_fencing_token"]
    assert result["payload"]["verified_checks"][0]["status"] == "PASS"
    assert result["payload_digest"] == _digest(result["payload"])
    assert result["recipient"] == "LivingSystem.AgenticHarness"
    # Result serialization is replay-safe; same run won't invent another reply.
    assert reply_to_wls(mailbox_root=mailbox, message_id="msg-A1", db_path=db)["status"] == "FAILED"
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



def test_one_command_wls_cycle_is_verified_and_returns_to_mailbox(
    tmp_path: Path, wls_task,
):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = make_shim(tmp_path)
    db = tmp_path / "cycle.db"
    done = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "result.txt",
        "--db", str(db), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "opencode", "--allow-model-usage",
        "--opencode-executable", str(executable),
    ])
    assert done.exit_code == 0, done.output
    result_paths = list((mailbox / "results").glob("*.json"))
    assert len(result_paths) == 1
    result = json.loads(result_paths[0].read_text(encoding="utf-8"))
    assert result["status"] == "SUCCEEDED"
    assert result["payload"]["verified_checks"][0]["status"] == "PASS"
    # Reentering after a process restart must return the same signed result,
    # not run the model worker again and double-charge usage.
    again = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "result.txt",
        "--db", str(db), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "opencode", "--allow-model-usage",
        "--opencode-executable", str(executable),
    ])
    assert again.exit_code == 0, again.output
    assert len(list((mailbox / "results").glob("*.json"))) == 1
    from agentbridge.persistence.database import Database
    from agentbridge.persistence.repository import AgentRepository

    storage = Database(db)
    storage.initialize()
    with storage.connect() as conn:
        state = AgentRepository(conn).get_runtime(_task_id(task))
    assert state.attempt_count == 1


def test_one_command_wls_cycle_denies_unapproved_model_use(
    tmp_path: Path, wls_task,
):
    mailbox, task, _ = wls_task
    denied = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(tmp_path), "--check-file", "out.txt",
        "--db", str(tmp_path / "cycle.db"), "--executor", "opencode",
    ])
    assert denied.exit_code == 2
    assert "requires --allow-model-usage" in denied.output
    assert not (tmp_path / "cycle.db").exists()



def test_fake_worker_cannot_complete_wls_even_with_preexisting_file(
    tmp_path: Path, wls_task,
):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "already-there.txt").write_text("not a worker result", encoding="utf-8")
    run = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "already-there.txt",
        "--db", str(tmp_path / "bridge.db"), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "fake",
    ])
    assert run.exit_code == 0, run.output
    reply = json.loads(next((mailbox / "results").glob("*.json")).read_text())
    assert reply["status"] == "FAILED"
    assert reply["payload"]["agentbridge_state"] == "COMPLETED"


def test_opencode_rejects_preexisting_file_before_dispatch(tmp_path: Path, wls_task):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "output.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        prepare_wls_task(
            mailbox_root=mailbox, message_id=task["message_id"],
            workspace=workspace, output=tmp_path / "request.json",
            check_file="output.txt", executor="opencode",
        )
    assert not (tmp_path / "request.json").exists()


def test_failing_executor_sends_wls_failure_instead_of_silence(
    tmp_path: Path, wls_task, monkeypatch,
):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = make_shim(tmp_path)
    monkeypatch.setenv("OPENCODE_SHIM_MODE", "fail")
    run = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "result.txt",
        "--db", str(tmp_path / "bridge.db"), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "opencode", "--allow-model-usage",
        "--opencode-executable", str(executable),
    ])
    assert run.exit_code != 0
    replies = list((mailbox / "results").glob("*.json"))
    assert len(replies) == 1
    reply = json.loads(replies[0].read_text())
    assert reply["status"] == "FAILED"
    assert reply["payload"]["agentbridge_state"] == "RECOVERY_REQUIRED"



def test_reenter_after_submit_does_not_reinsert_task(tmp_path, wls_task):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    contract = tmp_path / "to-agentbridge.json"
    db = tmp_path / "bridge.db"
    prepare = runner.invoke(app, [
        "wls-prepare", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--output", str(contract),
        "--check-file", "proof.txt", "--executor", "fake",
    ])
    assert prepare.exit_code == 0, prepare.output
    assert runner.invoke(app, [
        "submit", str(contract), "--db", str(db),
    ]).exit_code == 0
    # The canonical CLI uses wls-MESSAGE_ID.json in the DB's parent.
    saved = db.parent / f"wls-{task['message_id']}.json"
    saved.write_bytes(contract.read_bytes())
    result = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "proof.txt",
        "--db", str(db), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "fake",
    ])
    # The mock cannot produce a file; the verifier fails and a failed
    # result is stored for WLS instead of a duplicate-submit exception.
    assert result.exit_code != 0
    messages = list((mailbox / "results").glob("*.json"))
    assert len(messages) == 1
    assert json.loads(messages[0].read_text())["status"] == "FAILED"


def test_preexisting_result_after_prepare_is_blocked(tmp_path, wls_task):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    contract = tmp_path / f"wls-{task['message_id']}.json"
    prepare_wls_task(
        mailbox_root=mailbox, message_id=task["message_id"],
        workspace=workspace, output=contract, check_file="proof.txt",
        executor="opencode",
    )
    (workspace / "proof.txt").write_text("not a worker result", encoding="utf-8")
    result = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "proof.txt",
        "--db", str(tmp_path / "bridge.db"), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "opencode", "--allow-model-usage",
    ])
    assert result.exit_code == 2
    assert "Acceptance file already exists before worker start" in result.output
    assert not list((mailbox / "results").glob("*.json"))



def test_wls_cycle_independent_command_checks_real_worker_output(tmp_path, wls_task):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = make_shim(tmp_path)
    check = "python -c \"from pathlib import Path; assert Path('result.txt').read_text() == 'created by shim'\""
    args = [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "result.txt",
        "--verify-command", check, "--db", str(tmp_path / "cycle.db"),
        "--runs-dir", str(tmp_path / "runs"), "--executor", "opencode",
        "--allow-model-usage", "--opencode-executable", str(executable),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    reply = json.loads(next((mailbox / "results").glob("*.json")).read_text())
    assert reply["status"] == "SUCCEEDED"
    assert {c["check_id"] for c in reply["payload"]["verified_checks"]} == {
        "WLS_FILE_1", "WLS_COMMAND_1",
    }
    assert {c["status"] for c in reply["payload"]["verified_checks"]} == {"PASS"}
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert len(list((mailbox / "results").glob("*.json"))) == 1
    changed = list(args)
    changed[changed.index(check)] = 'python -c "print(42)"'
    rejected = runner.invoke(app, changed)
    assert rejected.exit_code != 0
    assert len(list((mailbox / "results").glob("*.json"))) == 1


def test_wls_cycle_failed_independent_command_never_claims_success(tmp_path, wls_task):
    mailbox, task, _ = wls_task
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = make_shim(tmp_path)
    result = runner.invoke(app, [
        "wls-cycle", task["message_id"], "--mailbox-root", str(mailbox),
        "--workspace", str(workspace), "--check-file", "result.txt",
        "--verify-command", 'python -c "import sys; sys.exit(7)"',
        "--db", str(tmp_path / "cycle.db"), "--runs-dir", str(tmp_path / "runs"),
        "--executor", "opencode", "--allow-model-usage",
        "--opencode-executable", str(executable),
    ])
    assert result.exit_code != 0
    reply = json.loads(next((mailbox / "results").glob("*.json")).read_text())
    assert reply["status"] == "FAILED"
    by_id = {c["check_id"]: c["status"] for c in reply["payload"]["verified_checks"]}
    assert by_id["WLS_FILE_1"] == "PASS"
    assert by_id["WLS_COMMAND_1"] == "FAIL"
