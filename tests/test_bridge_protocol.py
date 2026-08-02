from pathlib import Path

import pytest
from pydantic import ValidationError

from agentbridge.bridge.controller import BridgeConfig, compile_task
from agentbridge.bridge.protocol import BrainTaskMessage
from agentbridge.persistence.database import Database


def browser_task(**overrides) -> BrainTaskMessage:
    data = {
        "session_id": "AB-session-1",
        "request_id": "REQ-1",
        "title": "Bridge test",
        "goal": "Run the bounded bridge test",
        "constraints": ["Do not change unrelated files"],
        "acceptance": [
            {
                "id": "A1",
                "type": "command",
                "command": 'python -c "print(123)"',
                "expected_exit_code": 0,
            }
        ],
        "timeout_seconds": 30,
    }
    data.update(overrides)
    return BrainTaskMessage.model_validate(data)


def test_protocol_rejects_local_authority_fields() -> None:
    base = browser_task().model_dump(mode="json")
    for field, value in [
        ("workspace", "C:/private"),
        ("executor", "opencode"),
        ("permissions", {"shell": "allow"}),
        ("environment", {"SECRET": "x"}),
    ]:
        with pytest.raises(ValidationError):
            BrainTaskMessage.model_validate({**base, field: value})


def test_request_hash_is_canonical_and_content_sensitive() -> None:
    first = browser_task()
    same = BrainTaskMessage.model_validate(first.model_dump(mode="json"))
    changed = browser_task(goal="A different goal")
    assert first.request_hash() == same.request_hash()
    assert first.request_hash() != changed.request_hash()


def test_compile_applies_only_server_side_workspace_and_executor(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = BridgeConfig(
        workspace=workspace,
        database=Database(tmp_path / "bridge.db"),
        runs_dir=tmp_path / "runs",
        executor_name="opencode",
        max_timeout_seconds=15,
    )
    envelope = compile_task(browser_task(timeout_seconds=30), config)
    assert envelope.target.workspace == str(workspace.resolve())
    assert envelope.target.executor_id == "opencode"
    assert envelope.permissions.file_write.mode.value == "allow"
    assert envelope.permissions.delete.mode.value == "allow"
    assert envelope.permissions.network.mode.value == "allow"
    assert envelope.permissions.shell.mode.value == "allow"
    assert envelope.budget.timeout_seconds == 15
    assert envelope.source.conversation_ref == "AB-session-1"


def test_browser_contract_bounds_input_size() -> None:
    with pytest.raises(ValidationError):
        browser_task(goal="x" * 20_001)
    with pytest.raises(ValidationError):
        browser_task(acceptance=[])
    with pytest.raises(ValidationError):
        browser_task(timeout_seconds=3601)
