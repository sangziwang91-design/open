import hashlib
from pathlib import Path
from typing import Any

from agentbridge.domain.task import TaskEnvelope
from agentbridge.executors.base import Executor


class FakeExecutor(Executor):
    executor_id = "fake"

    def __init__(self, exit_code: int = 0, stdout: str = "fake executor completed\n") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self._running = False
        self._context: dict[str, Any] | None = None

    def prepare(self, envelope: TaskEnvelope, run_dir: Path) -> dict[str, Any]:
        run_dir.mkdir(parents=True, exist_ok=True)
        command = f"fake:{envelope.goal}"
        command_path = run_dir / "command.txt"
        command_path.write_text(command, encoding="utf-8")
        self._context = {
            "command": command,
            "command_hash": hashlib.sha256(command.encode()).hexdigest(),
            "workspace": envelope.target.workspace,
            "run_dir": str(run_dir),
        }
        return dict(self._context)

    def start(self, prepared_context: dict[str, Any]) -> int:
        self._context = prepared_context
        self._running = True
        return 4242

    def poll(self) -> bool:
        return self._running

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        if self._context is None:
            raise RuntimeError("executor was not prepared")
        run_dir = Path(self._context["run_dir"])
        (run_dir / "stdout.log").write_text(self.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        self._running = False
        return self.exit_code

    def collect(self) -> dict[str, Any]:
        if self._context is None:
            raise RuntimeError("executor was not prepared")
        run_dir = Path(self._context["run_dir"])
        return {
            "exit_code": self.exit_code,
            "stdout_path": str(run_dir / "stdout.log"),
            "stderr_path": str(run_dir / "stderr.log"),
            "command_path": str(run_dir / "command.txt"),
            "workspace": self._context["workspace"],
            "terminated": False,
        }

    def cancel(self) -> None:
        self._running = False
