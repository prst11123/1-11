import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base


@pytest.mark.asyncio
async def test_memory_database_is_shared_by_handler_threads(store):
    # Bootstrap runs on the main thread, while handlers use asyncio.to_thread.
    await asyncio.gather(*(asyncio.to_thread(store.touch_user, {"id": 7000 + i})
                           for i in range(16)))
    assert await asyncio.to_thread(store.can_create, 1001)
    assert all(store.user(7000 + i) is not None for i in range(16))


def test_migrations_round_trip_matches_models(config, tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migrations.db")
    for key, value in config.model_dump(by_alias=True).items():
        if value is not None:
            monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("DATABASE_URL", url)
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    for target in ("head", "base", "head"):
        (command.downgrade if target == "base" else command.upgrade)(cfg, target)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == "0006_guest_bindings"
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
