"""Database engine and transaction boundary; safe for multi-threaded handlers."""
from __future__ import annotations
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(url: str):
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=5 if not url.startswith("sqlite") else 5)


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        with self.Session() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def close(self):
        self.engine.dispose()
