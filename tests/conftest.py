from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentbridge.persistence.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "agentbridge.db")
    db.initialize()
    return db
