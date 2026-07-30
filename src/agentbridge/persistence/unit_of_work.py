import sqlite3
from types import TracebackType

from .database import Database


class UnitOfWork:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> "UnitOfWork":
        self.conn = self.database.connect()
        self.conn.execute("BEGIN")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        assert self.conn is not None
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()
        self.conn = None
        return False
