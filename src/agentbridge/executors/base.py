from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agentbridge.domain.task import TaskEnvelope


class Executor(ABC):
    executor_id: str

    @abstractmethod
    def prepare(self, envelope: TaskEnvelope, run_dir: Path) -> dict[str, Any]: ...

    @abstractmethod
    def start(self, prepared_context: dict[str, Any]) -> int: ...

    @abstractmethod
    def poll(self) -> bool: ...

    @abstractmethod
    def wait(self, timeout: int | None = None) -> int: ...

    @abstractmethod
    def collect(self) -> dict[str, Any]: ...

    @abstractmethod
    def cancel(self) -> None: ...
