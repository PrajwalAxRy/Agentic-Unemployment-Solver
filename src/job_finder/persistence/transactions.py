"""Composable SQLite transactions, including repository calls inside a batch commit."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def atomic(connection: sqlite3.Connection) -> Iterator[None]:
    """Own a write transaction, or a savepoint inside the caller's transaction."""
    nested = connection.in_transaction
    name = "transaction_" + uuid4().hex
    connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
    try:
        yield
        if nested:
            connection.execute(f"RELEASE {name}")
        else:
            connection.commit()
    except BaseException:
        if nested:
            connection.execute(f"ROLLBACK TO {name}")
            connection.execute(f"RELEASE {name}")
        else:
            connection.rollback()
        raise
