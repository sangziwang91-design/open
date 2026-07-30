from pathlib import Path

import pytest

from agentbridge.errors import ExecutorUnavailableError
from agentbridge.executors.opencode import OpenCodeExecutor
from tests.test_repository import sample_task


def test_missing_opencode_is_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agentbridge.executors.opencode.shutil.which", lambda _: None)
    with pytest.raises(ExecutorUnavailableError, match="not found"):
        OpenCodeExecutor().prepare(sample_task(), tmp_path)
