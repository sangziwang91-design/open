import hashlib
import shlex
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

from agentbridge.domain.task import TaskEnvelope
from agentbridge.errors import ExecutorUnavailableError
from agentbridge.executors.base import Executor


class OpenCodeExecutor(Executor):
    executor_id = "opencode"

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.stdout_file = None
        self.stderr_file = None
        self.context: dict[str, Any] | None = None

    def prepare(self, envelope: TaskEnvelope, run_dir: Path) -> dict[str, Any]:
        executable = shutil.which("opencode")
        if executable is None:
            raise ExecutorUnavailableError("opencode executable was not found on PATH")
        run_dir.mkdir(parents=True, exist_ok=True)
        workspace = str(Path(envelope.target.workspace).resolve())
        command = [
            executable,
            "run",
            "--format",
            "json",
            "--dir",
            workspace,
            envelope.goal,
        ]
        command_text = shlex.join(command)
        command_path = run_dir / "command.txt"
        command_path.write_text(command_text, encoding="utf-8")
        self.context = {
            "command": command,
            "command_hash": hashlib.sha256(command_text.encode()).hexdigest(),
            "workspace": workspace,
            "run_dir": str(run_dir),
        }
        return dict(self.context)

    def start(self, prepared_context: dict[str, Any]) -> int:
        self.context = prepared_context
        run_dir = Path(prepared_context["run_dir"])
        self.stdout_file = (run_dir / "stdout.log").open("w", encoding="utf-8")
        self.stderr_file = (run_dir / "stderr.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            prepared_context["command"],
            cwd=prepared_context["workspace"],
            stdout=self.stdout_file,
            stderr=self.stderr_file,
            text=True,
        )
        return int(self.process.pid)

    def poll(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def wait(self, timeout: int | None = None) -> int:
        if self.process is None:
            raise RuntimeError("executor was not started")
        return int(self.process.wait(timeout=timeout))

    def collect(self) -> dict[str, Any]:
        if self.process is None or self.context is None:
            raise RuntimeError("executor was not started")
        self._close_logs()
        exit_code = int(self.process.returncode)
        signal_name = None
        if exit_code < 0:
            try:
                signal_name = signal.Signals(-exit_code).name
            except ValueError:
                signal_name = "UNKNOWN"
        run_dir = Path(self.context["run_dir"])
        return {
            "exit_code": exit_code,
            "stdout_path": str(run_dir / "stdout.log"),
            "stderr_path": str(run_dir / "stderr.log"),
            "command_path": str(run_dir / "command.txt"),
            "workspace": self.context["workspace"],
            "terminated": exit_code < 0,
            "signal": signal_name,
        }

    def cancel(self) -> None:
        if self.process is not None and self.poll():
            self.process.kill()
            self.process.wait()
        self._close_logs()

    def _close_logs(self) -> None:
        for handle in (self.stdout_file, self.stderr_file):
            if handle is not None and not handle.closed:
                handle.close()
