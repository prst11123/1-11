import pytest
from app.config import Settings
from app.db import Database
from app.models import Base
from app.store import Store

@pytest.fixture
def config():
    return Settings(_env_file=None, BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456789",
                    DATABASE_URL="sqlite:///:memory:", ADMIN_IDS="1001,1002", OWNER_IDS="1001",
                    WEBHOOK_URL="https://example.up.railway.app",
                    WEBHOOK_SECRET="example_secrettoken_01234567890")

@pytest.fixture
def store(config):
    db=Database(config.database_url)
    Base.metadata.create_all(db.engine)
    st=Store(db,config)
    st.initialize_admins()
    yield st
    db.close()
