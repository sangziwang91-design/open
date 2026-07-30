from pathlib import Path

from agentbridge.executors.fake import FakeExecutor
from tests.test_repository import sample_task


def test_fake_executor_writes_evidence(tmp_path: Path) -> None:
    executor = FakeExecutor(stdout="done\n")
    context = executor.prepare(sample_task(), tmp_path)
    assert executor.start(context) == 4242
    assert executor.wait(1) == 0
    result = executor.collect()
    assert Path(result["stdout_path"]).read_text() == "done\n"
