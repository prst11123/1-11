"""Direct Business-chat commands; no real Telegram or media network calls."""
from datetime import datetime, timezone
from io import BytesIO
import pytest
from PIL import Image

from app.quick_offer import parse_quick_offer
from app.gift_images import image_url, jpeg_bytes, GiftImageUnavailable
from app.handlers import AppHandler
from app.models import Base
from app.db import Database
from app.config import Settings
from app.store import Store


def test_parse_business_command():
    parsed = parse_quick_offer("https://t.me/nft/PlushPepe-123\n1000\n15м")
    assert parsed and parsed.gift_name == "PlushPepe #123" and parsed.stars == 1000 and parsed.duration == 15
    assert parse_quick_offer("/offer https://t.me/nft/InputKey-25057 2500 2ч").duration == 120
    assert parse_quick_offer("https://t.me/nft/PlushPepe-123") is None
    assert parse_quick_offer("https://t.me/nft/PlushPepe-123 0 15") is None
    assert parse_quick_offer("https://example.com/nft/PlushPepe-123 1000 15") is None
    assert parse_quick_offer("123 stars 15m") is None
    assert parse_quick_offer("https://t.me/nft/PlushPepe-123 1000 999999м") is None


def test_derived_image_is_fixed_host():
    assert image_url("https://t.me/nft/PlushPepe-123") == "https://nft.fragment.com/gift/plushpepe-123.medium.jpg"
    with pytest.raises(ValueError):
        image_url("https://site.example/evil")
    picture = Image.new("RGB", (120, 120), "navy")
    raw = BytesIO()
    picture.save(raw, "PNG")
    assert jpeg_bytes(raw.getvalue())[:3] == b"\xff\xd8\xff"
    with pytest.raises(GiftImageUnavailable):
        jpeg_bytes(b"not an image")


class FakeTelegram:
    def __init__(self):
        self.remote={"id":"b_quick", "user":{"id":1001,"username":"owner"}, "is_enabled":True,"rights":{"can_reply":True}}
        self.calls=[]
    async def get_business_connection(self, cid):
        return self.remote
    async def send_media(self, chat_id, image_file_id, media_kind, caption, markup=None, business_id=None,
                         image_data=None, reply_to_message_id=None):
        self.calls.append((chat_id, image_file_id, business_id, caption, image_data, reply_to_message_id))
        return {"message_id": 7788, "photo":[{"file_id":"cached-nft-123"}]}
    async def send_message(self, chat_id, text, markup=None, business_id=None):
        self.calls.append(("owner_notification",chat_id,text))
        return {"message_id":999}


@pytest.fixture
def quick_store(config, tmp_path):
    cfg=Settings(_env_file=None, BOT_TOKEN=config.bot_token,
                 DATABASE_URL="sqlite:///"+str(tmp_path/"quick.db"),
                 ADMIN_IDS=config.admin_ids, OWNER_IDS=config.owner_ids,
                 WEBHOOK_URL=config.webhook_url, WEBHOOK_SECRET=config.webhook_secret)
    db=Database(cfg.database_url)
    Base.metadata.create_all(db.engine)
    st=Store(db,cfg)
    st.initialize_admins()
    yield st
    db.close()

@pytest.mark.asyncio
async def test_business_quick_offer_in_same_chat(quick_store: Store, config, monkeypatch):
    store = quick_store
    bot=FakeTelegram()
    handler=AppHandler(config, store, bot)
    store.connection_update(bot.remote)
    # A recipient first has to message the Business account (24-hour can_reply).
    client={"id":2002,"first_name":"Buyer","username":"buyer"}
    now=int(datetime.now(timezone.utc).timestamp())
    await handler.dispatch({"update_id":11,"business_message":{
        "business_connection_id":"b_quick", "message_id":40,"date":now,
        "from":client,"chat":{"id":2002,"type":"private"},"text":"hi"}})
    async def fake_fetch(url):
        assert url == "https://t.me/nft/PlushPepe-123"
        return b"jpeg data here"
    monkeypatch.setattr("app.handlers.fetch_gift_image",fake_fetch)
    msg={"business_connection_id":"b_quick", "message_id":41,"date":now,
         "from":{"id":1001,"username":"owner"},"chat":{"id":2002,"type":"private"},
         "text":"https://t.me/nft/PlushPepe-123\n1000\n15м"}
    await handler.dispatch({"update_id":12,"business_message":msg})
    assert len(bot.calls)==1
    assert bot.calls[0][0]==2002 and bot.calls[0][2]=="b_quick"
    assert bot.calls[0][4]==b"jpeg data here" and bot.calls[0][5]==41
    assert "PlushPepe #123" in bot.calls[0][3] and "DEMO" in bot.calls[0][3]
    offers=store.offers_by_creator(1001)[1]
    assert len(offers)==1
    o=offers[0]
    assert o.status=="active" and o.recipient_chat_id==2002
    assert o.gift_image_file_id=="cached-nft-123"
    assert o.source_message_id==41
    # Telegram redelivers a semantically identical command with a new update id.
    await handler.dispatch({"update_id":13,"business_message":msg})
    assert len(bot.calls)==1
    assert len(store.offers_by_creator(1001)[1])==1
    # Customer cannot create a new offer just by sending three values.
    await handler.dispatch({"update_id":14,"business_message":{
        **msg,"message_id":42,"from":client}})
    assert len(bot.calls)==1
    assert len(store.offers_by_creator(1001)[1])==1
    # An owner-supplied photo in the caption is also accepted (no CDN call).
    image_msg = {**msg,"message_id":43,"text":None,"caption":"https://t.me/nft/InputKey-25057 500 5",
                 "photo":[{"file_id":"trusted_uploaded_image"}]}
    await handler.dispatch({"update_id":15,"business_message":image_msg})
    assert len(bot.calls)==2
    assert bot.calls[1][1]=="trusted_uploaded_image" and bot.calls[1][4] is None


@pytest.mark.asyncio
async def test_no_offer_without_recent_client_message(quick_store: Store, config, monkeypatch):
    store = quick_store
    bot=FakeTelegram()
    handler=AppHandler(config,store,bot)
    store.connection_update(bot.remote)
    now=int(datetime.now(timezone.utc).timestamp())
    await handler.dispatch({"update_id":51,"business_message":{
        "business_connection_id":"b_quick","message_id":1,"date":now,
        "from":{"id":1001},"chat":{"id":2002,"type":"private"},
        "text":"https://t.me/nft/PlushPepe-123 1000 15"}})
    assert len(store.offers_by_creator(1001)[1])==0
