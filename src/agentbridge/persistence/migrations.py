from .database import Database


def migrate(database: Database) -> None:
    database.initialize()
