"""Database engine and transaction boundary; safe for multi-threaded handlers."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
from threading import RLock
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def is_memory_sqlite(url: str) -> bool:
    parsed = make_url(url)
    return parsed.get_backend_name() == "sqlite" and parsed.database in {None, "", ":memory:"}


def make_engine(url: str):
    if is_memory_sqlite(url):
        # asyncio.to_thread must see the same in-memory database as bootstrap.
        return create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=5)


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        # A shared SQLite connection cannot host simultaneous transactions.
        self._transaction_lock = RLock() if is_memory_sqlite(url) else nullcontext()

    @contextmanager
    def transaction(self):
        with self._transaction_lock, self.Session() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def close(self):
        self.engine.dispose()
