from datetime import timedelta
import pytest
from app.states import validate_gift_url,parse_stars,parse_duration,utcnow,assert_transition
from app.store import DomainError
from app.models import BusinessChat, BusinessConnection
from app.config import Settings


def setup_business(st, owner=1001, recipient=2002, seconds_ago=3):
    with st.db.transaction() as s:
        s.add(BusinessConnection(business_connection_id="bc-test",owner_user_id=owner,active=True,permissions={"can_reply":True},
                                 connected_at=utcnow(),updated_at=utcnow()))
        s.add(BusinessChat(business_connection_id="bc-test",chat_id=recipient,user_id=recipient,first_name="Test",
                           active=True,last_incoming_at=utcnow()-timedelta(seconds=seconds_ago),last_activity_at=utcnow()))


def test_validation():
    assert validate_gift_url("https://t.me/nft/PlushPepe-123") == "https://t.me/nft/PlushPepe-123"
    for v in ("http://t.me/nft/a", "https://t.me/bot/start", "https://evil.com/nft/test", "https://t.me/nft/abc?x=1"):
        with pytest.raises(ValueError):validate_gift_url(v)
    assert parse_stars("1000")==1000
    for v in ("0","-1","1.5","99999999999999","abc"):
        with pytest.raises(ValueError):parse_stars(v)
    assert parse_duration("1h")==60
    assert parse_duration("15")==15
    with pytest.raises(ValueError):parse_duration("0")
    with pytest.raises(ValueError):parse_duration("8h15m")


def test_transition_rules():
    now=utcnow()
    assert assert_transition("active","accept",now+timedelta(minutes=5))=="accepted"
    with pytest.raises(ValueError):assert_transition("accepted","accept",now+timedelta(minutes=5))
    with pytest.raises(ValueError):assert_transition("active","accept",now-timedelta(seconds=1))
    assert assert_transition("accepted","transfer",now-timedelta(days=1))=="transfer_requested"


def test_role_bootstrap(store):
    assert store.user(1001).role=="owner"
    assert store.user(1002).role=="admin"
    with pytest.raises(DomainError):store.set_user_access(1002,1001,"block")
    with pytest.raises(DomainError):store.set_user_access(1002,5005,"promote")
    u=store.set_user_access(1001,5005,"allow")
    assert u.allowed
    store.set_user_access(1001,5005,"block")
    assert not store.can_create(5005)
    store.set_user_access(1001,5005,"unblock")
    assert store.can_create(5005)


def test_business_target_and_offer_state(store):
    setup_business(store)
    t=store.resolve_target(1001)
    assert t["chat_id"]==2002
    p={"gift_url":"https://t.me/nft/PlushPepe-123","gift_name":"Plush Pepe #123","stars":1000,"duration":30}
    o=store.create_offer(1001,p)
    assert o.delivery_status=="sending" and o.status=="draft"
    store.mark_sent(o.id,42)
    o,expired=store.offer_transition(o.id,2002,"accept")
    assert o.status=="accepted" and not expired
    with pytest.raises(DomainError):store.offer_transition(o.id,2002,"accept")
    with pytest.raises(DomainError):store.offer_transition(o.id,2003,"transfer")
    o,expired=store.offer_transition(o.id,2002,"transfer")
    assert o.status=="transfer_requested"
    assert store.stats()["transfer_requested"]==1
    with pytest.raises(DomainError):store.offer_transition(o.id,2002,"decline")


def test_expiration_survives_restart(store):
    setup_business(store)
    p={"gift_url":"https://t.me/nft/Foo-100","gift_name":"Foo","stars":1,"duration":5}
    o=store.create_offer(1001,p)
    store.mark_sent(o.id,15)
    with store.db.transaction() as s:
        entry=s.get(type(o),o.id)
        entry.expires_at=utcnow()-timedelta(seconds=1)
    assert store.due_offers()==[o.id]
    assert store.due_offers()==[]
    assert store.offer(o.id).status=="expired"
    with pytest.raises(DomainError):store.offer_transition(o.id,2002,"accept")


def test_target_stale(store):
    setup_business(store,seconds_ago=25*3600)
    with pytest.raises(DomainError):store.resolve_target(1001)


def test_target_config_precedence(config):
    new=Settings(_env_file=None,BOT_TOKEN=config.bot_token,DATABASE_URL=config.database_url,
                 ADMIN_IDS=config.admin_ids,WEBHOOK_URL=config.webhook_url,WEBHOOK_SECRET=config.webhook_secret,
                 TARGET_CHAT_ID="222222",TARGET_USER_ID="111111")
    assert new.target_chat_id==222222


def test_callback_dedupe(store):
    assert store.register_callback("abc")
    assert not store.register_callback("abc")
    assert store.register_update(345)
    assert not store.register_update(345)


def test_uncertain_delivery_cannot_be_cancelled_or_retried(store):
    setup_business(store)
    p={"gift_url":"https://t.me/nft/G-1","gift_name":"G","stars":1,"duration":10}
    o=store.create_offer(1001,p)
    with pytest.raises(DomainError):store.cancel_offer(o.id,1001)
    store.mark_unknown(o.id,"timeout")
    assert store.offer(o.id).delivery_status=="unknown"
    with pytest.raises(DomainError):store.retry_send(o.id,1001)
    with pytest.raises(DomainError):store.cancel_offer(o.id,1001)


def test_redeploy_target_change_no_source_edit(tmp_path,config):
    db_path="sqlite:///"+str(tmp_path/"target.db")
    from app.db import Database
    from app.models import Base
    from app.store import Store
    d=Database(db_path)
    Base.metadata.create_all(d.engine)
    c1=Settings(_env_file=None,BOT_TOKEN=config.bot_token,DATABASE_URL=db_path,
                ADMIN_IDS="1001",WEBHOOK_URL=config.webhook_url,WEBHOOK_SECRET=config.webhook_secret,
                TARGET_CHAT_ID=2002)
    s1=Store(d,c1)
    s1.initialize_admins()
    setup_business(s1,recipient=2002)
    with d.transaction() as session:
        session.add(BusinessChat(business_connection_id="bc-test",chat_id=3003,user_id=3003,
                                 first_name="Other",active=True,last_incoming_at=utcnow(),last_activity_at=utcnow()))
    assert s1.resolve_target(1001)["chat_id"] == 2002
    c2=Settings(_env_file=None,BOT_TOKEN=config.bot_token,DATABASE_URL=db_path,
                ADMIN_IDS="1001",WEBHOOK_URL=config.webhook_url,WEBHOOK_SECRET=config.webhook_secret,
                TARGET_CHAT_ID=3003)
    s2=Store(d,c2)
    assert s2.resolve_target(1001)["chat_id"] == 3003
    d.close()
