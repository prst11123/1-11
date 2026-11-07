import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from app.config import Settings
from app.db import Database
from app.models import Base
from app.store import Store
from app.handlers import AppHandler


class FakeTelegram:
    def __init__(self):
        self.calls=[]
        self.counter=100
        self.remote={"id":"b_test","user":{"id":1001,"username":"owner"},"is_enabled":True,"rights":{"can_reply":True}}

    async def get_business_connection(self,cid):
        return self.remote

    async def send_message(self,chat_id,text,markup=None,business_id=None):
        self.calls.append(("send_message",chat_id,business_id,text,markup))
        self.counter+=1
        return {"message_id":self.counter}

    async def send_media(self,chat_id,image_file_id,media_kind,caption,markup=None,business_id=None):
        self.calls.append(("send_media",chat_id,business_id,caption,markup))
        self.counter+=1
        return {"message_id":self.counter}

    async def answer_callback(self,cid,text="",alert=False):
        self.calls.append(("answer_callback",cid,text,alert))
        return True

    async def edit_caption(self,offer,caption,markup):
        self.calls.append(("edit_caption",offer.recipient_chat_id,offer.business_connection_id,caption,markup))
        return True


@pytest.mark.asyncio
async def test_end_to_end_business_offer_demo(config,tmp_path):
    cfg=Settings(_env_file=None,BOT_TOKEN=config.bot_token, DATABASE_URL="sqlite:///"+str(tmp_path/"live.db"),
                 ADMIN_IDS=config.admin_ids,OWNER_IDS=config.owner_ids,WEBHOOK_URL=config.webhook_url,
                 WEBHOOK_SECRET=config.webhook_secret)
    db=Database(cfg.database_url)
    Base.metadata.create_all(db.engine)
    store=Store(db,cfg)
    store.initialize_admins()
    fake=FakeTelegram()
    handler=AppHandler(cfg,store,fake)
    user={"id":1001,"first_name":"Owner","username":"owner"}
    recipient={"id":2002,"first_name":"Recipient","username":"buyer"}
    seq=0

    async def dispatch(message):
        nonlocal seq
        seq+=1
        await handler.dispatch({"update_id":seq,**message})

    async def send_text(text):
        await dispatch({"message":{"message_id":seq+1,"from":user,"chat":{"id":1001,"type":"private"},"text":text}})

    async def cb(actor,data,chat_id=1001,msg_id=1):
        await dispatch({"callback_query":{"id":f"c-{seq+1}","from":actor,"data":data,
                                          "message":{"message_id":msg_id,"chat":{"id":chat_id,"type":"private"}}}})

    await dispatch({"business_connection":fake.remote})
    await dispatch({"business_message":{"message_id":10,"business_connection_id":"b_test",
                                        "chat":{"id":2002,"type":"private"},"from":recipient,
                                        "date":int(datetime.now(timezone.utc).timestamp()),"text":"hi"}})
    await send_text("/start")
    await send_text("/create")
    await send_text("https://t.me/nft/InputKey-25057")
    await send_text("1000")
    await send_text("30")
    await send_text("Пропустить")
    await send_text("Input Key #25057")
    await cb(user,"flow:target:auto")
    await cb(user,"flow:send")

    sent=[x for x in fake.calls if x[0]=="send_media" and x[1]==2002]
    assert len(sent)==1, "must actually send one media message to recipient business chat"
    assert sent[0][2]=="b_test"
    assert "DEMO" in sent[0][3] and "1 000 Stars" in sent[0][3]
    o=store.offers_by_creator(1001)[1][0]
    assert o.delivery_status=="sent" and o.status=="active" and o.telegram_message_id
    await cb(recipient,f"offer:accept:{o.id}",2002,o.telegram_message_id)
    assert store.offer(o.id).status=="accepted"
    await cb(recipient,f"offer:instructions:{o.id}",2002,o.telegram_message_id)
    assert store.stats()["instructions"] == 1
    await cb(recipient,f"offer:transfer:{o.id}",2002,o.telegram_message_id)
    assert store.offer(o.id).status=="accepted"  # Legacy transfer button cannot trigger a transfer
    assert store.stats()["offers_sent"]==1
    assert store.stats()["offers_created"]==1
    assert any(x[0]=="edit_caption" and "Stars не списаны" in x[3] for x in fake.calls)
    assert not any(x[0]=="send_message" and x[1]==2002 and "Подарок не списывается" in x[3] for x in fake.calls)
    db.close()
