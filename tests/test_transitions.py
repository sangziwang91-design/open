import pytest

from agentbridge.control.transitions import validate_transition
from agentbridge.domain.enums import TaskState
from agentbridge.errors import InvalidTransitionError


def test_valid_transition() -> None:
    assert validate_transition(TaskState.RECEIVED, TaskState.VALIDATING)


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(TaskState.READY, TaskState.COMPLETED)
