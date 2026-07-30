import pytest
from pydantic import ValidationError

from agentbridge.domain.task import TaskEnvelope

BASE = {
    "schemaversion": "1.0",
    "title": "x",
    "type": "engineering",
    "goal": "do x",
    "source": {"adapter": "manual"},
    "target": {"executorid": "fake", "workspace": "."},
    "acceptance": [{"id": "A1", "type": "command", "command": "python -V"}],
    "stop": {"success": "pass", "blocked": "blocked"},
}


def test_compact_aliases_are_accepted() -> None:
    task = TaskEnvelope.model_validate(BASE)
    assert task.schema_version == "1.0"
    assert task.target.executor_id == "fake"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskEnvelope.model_validate({**BASE, "surprise": True})


def test_command_acceptance_requires_command() -> None:
    bad = {**BASE, "acceptance": [{"id": "A1", "type": "command"}]}
    with pytest.raises(ValidationError):
        TaskEnvelope.model_validate(bad)


@pytest.mark.parametrize(
    "acceptance",
    [
        [
            {"id": "A1", "type": "command", "command": "python -V"},
            {"id": "A1", "type": "fileexists", "path": "README.md"},
        ],
        [{"id": "../escape", "type": "fileexists", "path": "README.md"}],
        [{"id": "A1", "type": "gitdiff", "rule": "anything_else"}],
        [{"id": "A1", "type": "schema"}],
    ],
)
def test_unsupported_or_ambiguous_acceptance_is_rejected(acceptance) -> None:
    with pytest.raises(ValidationError):
        TaskEnvelope.model_validate({**BASE, "acceptance": acceptance})


def test_unknown_executor_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskEnvelope.model_validate(
            {**BASE, "target": {"executorid": "typo", "workspace": "."}}
        )
