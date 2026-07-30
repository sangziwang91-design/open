import pytest

from agentbridge.persistence.unit_of_work import UnitOfWork


def test_commit(database) -> None:
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        uow.conn.execute(
            "INSERT INTO capability_snapshots VALUES (?, ?, ?)", ("S1", "{}", "now")
        )
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM capability_snapshots").fetchone()[0] == 1


def test_rollback(database) -> None:
    with pytest.raises(RuntimeError):
        with UnitOfWork(database) as uow:
            assert uow.conn is not None
            uow.conn.execute(
                "INSERT INTO capability_snapshots VALUES (?, ?, ?)", ("S1", "{}", "now")
            )
            raise RuntimeError("rollback")
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM capability_snapshots").fetchone()[0] == 0
