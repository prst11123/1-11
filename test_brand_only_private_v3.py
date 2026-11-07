from datetime import timedelta
from types import SimpleNamespace
import pytest
from app.render import BRAND, offer_caption, preview_caption, instructions
from app.states import utcnow
from app.handlers import AppHandler
from app.config import Settings
from app.db import Database
from app.models import Base
from app.store import Store


def offer(status):
    return SimpleNamespace(status=status,gift_name='PlushPepe #123',gift_url='https://t.me/nft/PlushPepe-123',stars_amount=1000,expires_at=utcnow()+timedelta(minutes=15))


def test_no_branding_in_sent_offer_or_preview():
    for status in ('draft','active','accepted','declined','expired','transfer_requested'):
        assert BRAND not in offer_caption(offer(status))
    assert BRAND not in preview_caption({'gift_url':'https://t.me/nft/PlushPepe-123','gift_name':'PlushPepe #123','stars':1000,'duration':15},{'name':'Test','chat_id':100,'source':'Railway'})


def test_no_branding_or_contact_in_business_instructions():
    text=instructions('ru',contact_username='abcdef')
    assert BRAND not in text
    assert 'abcdef' not in text
    assert 'DEMO' in text


@pytest.mark.asyncio
async def test_branding_and_support_contact_shown_only_in_private_bot_help(config, tmp_path):
    class Telegram:
        def __init__(self):self.sent=[]
        async def send_message(self,chat_id,text,markup=None,business_id=None):
            self.sent.append((chat_id,text,business_id))
    tg=Telegram()
    cfg=Settings(_env_file=None,BOT_TOKEN=config.bot_token, DATABASE_URL="sqlite:///"+str(tmp_path/"brandtest.db"),
                 ADMIN_IDS=config.admin_ids,OWNER_IDS=config.owner_ids,WEBHOOK_URL=config.webhook_url,WEBHOOK_SECRET=config.webhook_secret)
    db=Database(cfg.database_url)
    Base.metadata.create_all(db.engine)
    store=Store(db,cfg)
    store.initialize_admins()
    handler=AppHandler(cfg,store,tg)
    store.set_display_contact(1001,'abcdef')
    await handler.on_message({'chat':{'id':1001,'type':'private'},'from':{'id':1001,'username':'owner'},'text':'/help'})
    assert tg.sent and tg.sent[-1][0]==1001
    assert BRAND in tg.sent[-1][1]
    assert '@abcdef' in tg.sent[-1][1]
    assert tg.sent[-1][2] is None
    db.close()
