from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("AGENTBRIDGE_DB", "agentbridge.db"))
    runs_dir: Path = Path(os.getenv("AGENTBRIDGE_RUNS_DIR", "data/runs"))
