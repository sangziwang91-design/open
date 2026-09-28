import sqlite3

import pytest

from agentbridge.persistence.unit_of_work import UnitOfWork


def test_database_connection_context_closes_file_handle(database) -> None:
    connection = database.connect()
    with connection as conn:
        conn.execute("SELECT 1").fetchone()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_commit(database) -> None:
    with UnitOfWork(database) as uow:
        assert uow.conn is not None
        uow.conn.execute(
            "INSERT INTO capability_snapshots VALUES (?, ?, ?)", ("S1", "{}", "now")
        )
    with database.connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM capability_snapshots").fetchone()[0] == 1
        )


def test_rollback(database) -> None:
    with pytest.raises(RuntimeError), UnitOfWork(database) as uow:
        assert uow.conn is not None
        uow.conn.execute(
            "INSERT INTO capability_snapshots VALUES (?, ?, ?)", ("S1", "{}", "now")
        )
        raise RuntimeError("rollback")
    with database.connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM capability_snapshots").fetchone()[0] == 0
        )
