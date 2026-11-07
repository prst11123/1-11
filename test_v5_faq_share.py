"""V5 regressions for test-first menu, inline in ordinary chats and FAQ admin editing."""
import json

import pytest

from app import keyboards as kb
from app.handlers import AppHandler
from app.store import DomainError, Store
from app.db import Database
from app.models import Base, AdminAudit


@pytest.fixture
def v5_store(config, tmp_path):
    db = Database("sqlite:///"+str(tmp_path/"v5.db"))
    Base.metadata.create_all(db.engine)
    store = Store(db, config)
    store.initialize_admins()
    yield store
    db.close()


class Bot:
    def __init__(self):
        self.messages=[]
        self.media=[]
        self.inline=[]
        self.callbacks=[]

    async def send_message(self, chat_id, text, markup=None, business_id=None):
        self.messages.append((chat_id,text,markup,business_id))
        return {"message_id":1}

    async def send_media(self, chat_id, file_id, media_kind, caption, markup=None, **kwargs):
        self.media.append((chat_id,caption,markup,kwargs))
        return {"message_id":2}

    async def answer_inline(self, qid, results):
        self.inline.append((qid,results))
        return True

    async def answer_callback(self, cid, text="", alert=False):
        self.callbacks.append((cid,text,alert))
        return True


def test_menu_replaces_create_with_test_and_faq():
    names=[b['text'] for row in kb.main_menu(True)['keyboard'] for b in row]
    assert "🎁 Создать офер" not in names
    assert "🧪 Тест офера" in names
    assert "📤 В любой чат" in names
    assert "❓ FAQ" in names
    assert "✏️ FAQ" in json.dumps(kb.admin_keyboard(),ensure_ascii=False)
    assert any('switch_inline_query' in b for row in kb.test_offer_keyboard()['inline_keyboard'] for b in row)


@pytest.mark.asyncio
async def test_test_button_does_not_require_business_connection(config,v5_store):
    bot=Bot()
    h=AppHandler(config,v5_store,bot)
    await h.on_message({"chat":{"type":"private","id":1001},"from":{"id":1001},"text":"🧪 Тест офера"})
    assert len(bot.media)==1
    assert "DEMO" in bot.media[-1][1]
    assert bot.media[-1][0]==1001
    assert any('switch_inline_query' in b for row in bot.media[-1][2]['inline_keyboard'] for b in row)


@pytest.mark.asyncio
async def test_empty_inline_query_is_sendable_in_any_chat(config,v5_store):
    bot=Bot()
    h=AppHandler(config,v5_store,bot)
    await h.dispatch({"update_id":501,"inline_query":{"id":"qid-5","from":{"id":1001},"query":""}})
    assert len(bot.inline)==1
    results=bot.inline[0][1]
    assert results and results[0]['type']=='article'
    assert "DEMO" in results[0]['input_message_content']['message_text']
    assert all('business_connection_id' not in r for r in results)
    assert len(results)==2


@pytest.mark.asyncio
async def test_faq_button_and_support_from_database(config,v5_store):
    bot=Bot()
    h=AppHandler(config,v5_store,bot)
    faq='Информация о тестах\nЕсли ошибка — сообщите поддержке\nНе переводите подарки для проверки.'
    v5_store.set_faq_text(1002,faq)
    v5_store.set_display_contact(1002,'support_team')
    await h.on_message({"chat":{"id":1001,"type":"private"},"from":{"id":1001},"text":"❓ FAQ"})
    assert faq in bot.messages[-1][1]
    assert '@support_team' in bot.messages[-1][1]
    assert "Бот от A/X T’eams" in bot.messages[-1][1]
    assert "DEMO" in bot.messages[-1][1]


def test_admin_can_change_faq_contact_but_user_cannot(v5_store):
    text='<b>Test</b> '+('sample FAQ description. '*25)
    faq=v5_store.set_faq_text(1002,text)
    assert faq==text.strip()
    assert v5_store.display_faq()==text.strip()
    assert v5_store.set_display_contact(1002,'faq_support')==('faq_support','Админ-панель')
    v5_store.touch_user({'id':2002,'first_name':'Other'},True)
    with pytest.raises(DomainError):
        v5_store.set_faq_text(2002,'Text that should never be shown to users')
    with pytest.raises(DomainError):
        v5_store.set_display_contact(2002,'another_user')
    with pytest.raises(DomainError):
        v5_store.set_faq_text(1002,'a')
    with pytest.raises(DomainError):
        v5_store.set_faq_text(1002,'x'*3001)
    assert v5_store.set_faq_text(1002,None)==v5_store.DEFAULT_FAQ


@pytest.mark.asyncio
async def test_admin_faq_edit_full_flow(config,v5_store):
    bot=Bot()
    h=AppHandler(config,v5_store,bot)
    cb={"id":"faqcb","from":{"id":1002},"data":"admin:faqedit",
        "message":{"message_id":1,"chat":{"id":1002,"type":"private"}}}
    await h.on_callback(cb)
    assert v5_store.flow(1002)[0]=="ADMIN_FAQ_INPUT"
    faq='Как получить тестовый офер?\nНажмите /test.\nStars в DEMO не списываются.'
    await h.on_message({"chat":{"id":1002,"type":"private"},"from":{"id":1002},"text":faq})
    assert v5_store.display_faq()==faq
    assert v5_store.flow(1002)[0] is None
    assert any('FAQ сохранён' in m[1] for m in bot.messages)
    with v5_store.db.transaction() as s:
        assert s.query(AdminAudit).filter_by(action='FAQ_UPDATED').count()==1

@pytest.mark.asyncio
async def test_business_demo_trigger_edits_own_message_without_fragment(config,v5_store):
    """Owner can test from an authorized Business chat using an explicit trigger."""
    from datetime import datetime,timezone
    class BizBot(Bot):
        def __init__(self):
            super().__init__()
            self.edits=[]
        async def get_business_connection(self, cid):
            return {"id":cid,"user":{"id":1001},"is_enabled":True,
                    "rights":{"can_reply":True,"can_delete_all_messages":False}}
        async def edit_business_offer(self, chat_id, msgid, bizid, kind, raw, fileid, caption, markup):
            self.edits.append((chat_id,msgid,bizid,kind,raw,caption))
            return {"message_id":msgid,"photo":[{"file_id":"fixture-id"}]}
    bot=BizBot()
    h=AppHandler(config,v5_store,bot)
    ts=int(datetime.now(timezone.utc).timestamp())
    await h.dispatch({"update_id":801,"business_connection":await bot.get_business_connection('biz-a')})
    await h.dispatch({"update_id":802,"business_message":{
        "business_connection_id":"biz-a","message_id":30,"date":ts,
        "chat":{"id":2002,"type":"private"},"from":{"id":2002},"text":"hi"}})
    await h.dispatch({"update_id":803,"business_message":{
        "business_connection_id":"biz-a","message_id":31,"date":ts,
        "chat":{"id":2002,"type":"private"},"from":{"id":1001},"text":"#тестофер"}})
    assert len(bot.edits)==1
    edit=bot.edits[0]
    assert edit[0:4]==(2002,31,'biz-a','text')
    assert edit[4].startswith(b'\xff\xd8')  # valid JPEG, not a remote website request
    assert 'DEMO' in edit[5] and 'Бот от' not in edit[5]


@pytest.mark.asyncio
async def test_non_authorized_business_messages_are_not_changed(config,v5_store):
    from datetime import datetime,timezone
    class BizBot(Bot):
        async def get_business_connection(self,cid):
            return {"id":cid,"user":{"id":1001},"is_enabled":True,
                    "rights":{"can_reply":True}}
        async def edit_business_offer(self,*args,**kwargs):
            raise AssertionError('must not modify unrelated chat messages')
    bot=BizBot()
    h=AppHandler(config,v5_store,bot)
    ts=int(datetime.now(timezone.utc).timestamp())
    await h.dispatch({"update_id":811,"business_connection":await bot.get_business_connection('biz-b')})
    await h.dispatch({"update_id":812,"business_message":{
        "business_connection_id":"biz-b","message_id":34,"date":ts,
        "chat":{"id":2004,"type":"private"},"from":{"id":2004},"text":"#тестофер"}})
    assert not bot.media

@pytest.mark.asyncio
async def test_share_message_uses_real_bot_username(config,v5_store):
    class IdentifiedBot(Bot):
        async def api(self,method):
            assert method=='getMe'
            return {"username":"DemoNFTBot"}
    bot=IdentifiedBot()
    h=AppHandler(config,v5_store,bot)
    await h.on_message({"chat":{"id":1001,"type":"private"},"from":{"id":1001},"text":"📤 В любой чат"})
    msg=bot.messages[-1][1]
    assert '@DemoNFTBot' in msg
    assert 'Business' not in msg
    assert 'выберите карточку' in msg
