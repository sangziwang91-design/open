import sqlite3
from types import TracebackType
from typing import Literal, Self

from .database import Database


class UnitOfWork:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.conn: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("UnitOfWork is not active")
        return self.conn

    def __enter__(self) -> Self:
        self.conn = self.database.connect()
        self.conn.execute("BEGIN")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        connection = self.connection
        if exc_type is None:
            connection.commit()
        else:
            connection.rollback()
        connection.close()
        self.conn = None
        return False
