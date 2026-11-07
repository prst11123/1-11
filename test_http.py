from aiohttp.test_utils import TestClient, TestServer
import pytest
from app.main import make_app, STORE_KEY, TELEGRAM_KEY, HANDLER_KEY, READY_KEY
from app.config import Settings
from app.models import Base
from app.handlers import AppHandler
from test_integration import FakeTelegram


@pytest.mark.asyncio
async def test_webhook_secret_and_health(config,tmp_path):
    cfg=Settings(_env_file=None,BOT_TOKEN=config.bot_token,DATABASE_URL="sqlite:///"+str(tmp_path/"http.db"),
                 ADMIN_IDS="1001",OWNER_IDS="1001",WEBHOOK_URL=config.webhook_url,WEBHOOK_SECRET=config.webhook_secret)
    app=make_app(cfg)
    Base.metadata.create_all(app[STORE_KEY].db.engine)
    app[STORE_KEY].initialize_admins()
    fake=FakeTelegram()
    app[TELEGRAM_KEY]=fake
    app[HANDLER_KEY]=AppHandler(cfg,app[STORE_KEY],fake)
    app.on_startup.clear()
    app.on_cleanup.clear()
    app[READY_KEY]=True
    async with TestClient(TestServer(app)) as client:
        response=await client.get("/health")
        assert response.status==200
        assert (await response.json())["status"]=="ok"
        response=await client.post("/telegram/webhook",json={"update_id":1},headers={"X-Telegram-Bot-Api-Secret-Token":"wrong"})
        assert response.status==403
        response=await client.post("/telegram/webhook",json={"update_id":2})
        assert response.status==403
        response=await client.post("/telegram/webhook",json={"update_id":3},headers={"X-Telegram-Bot-Api-Secret-Token":cfg.webhook_secret})
        assert response.status==200
        assert (await response.json())["ok"]
    app[STORE_KEY].db.close()
