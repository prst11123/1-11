from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app import gift_images
from app.handlers import AppHandler
from app.models import BusinessChat, BusinessConnection
from app.quick_offer import parse_quick_offer
from app.states import utcnow
from app.store import DomainError


def test_dash_offer_and_malformed_url_do_not_crash():
    assert parse_quick_offer('-офер https://t.me/nft/InputKey-25057 1900 15').stars == 1900
    assert parse_quick_offer('https://t.me/NFT/InputKey-25057 1900 15') is None


@pytest.mark.parametrize('operation', ['refresh', 'retry'])
def test_revoked_creator_cannot_send_existing_offer(store, operation):
    store.set_user_access(1001, 3003, 'allow')
    with store.db.transaction() as session:
        session.add(BusinessConnection(business_connection_id='regression', owner_user_id=3003,
                                       active=True, permissions={'can_reply': True}))
        session.flush()
        session.add(BusinessChat(business_connection_id='regression', chat_id=2002,
                                 user_id=2002, active=True, last_incoming_at=utcnow()))
    offer = store.create_offer(3003, {'gift_url': 'https://t.me/nft/InputKey-25057',
                                     'gift_name': 'Input Key', 'stars': 1900, 'duration': 15})
    if operation == 'retry':
        store.mark_failed(offer.id, 'denied')
    store.set_user_access(1001, 3003, 'revoke')
    with pytest.raises(DomainError):
        if operation == 'refresh':
            store.refresh_send_authorization(offer.id)
        else:
            store.retry_send(offer.id, 3003)


@pytest.mark.asyncio
async def test_business_callback_rejects_same_ids_in_another_connection(config):
    offer = SimpleNamespace(id=1, recipient_chat_id=2002, telegram_message_id=42,
                            business_connection_id='original')
    handler = AppHandler(config, None, None)
    async def fake_db(name, *args):
        assert name == 'offer'  # no transition may be performed
        return offer
    handler.db = fake_db
    with pytest.raises(DomainError, match='Business'):
        await handler.offer_callback(2002, 'c1', 'offer:accept:1', {'message': {
            'chat': {'id': 2002}, 'message_id': 42, 'business_connection_id': 'other'}})


@pytest.mark.asyncio
async def test_business_bot_echo_does_not_create_offer(config):
    handler = AppHandler(config, None, None)
    await handler.on_business_quick_offer({'chat': {'type': 'private'},
        'sender_business_bot': {'id': 123}, 'text': 'https://t.me/nft/InputKey-25057 1900 15'})


@pytest.mark.asyncio
@pytest.mark.parametrize('oversize', [False, True])
async def test_nft_download_reads_all_chunks_with_size_bound(monkeypatch, oversize):
    output = BytesIO()
    Image.new('RGB', (16, 16), 'navy').save(output, 'PNG')
    raw = output.getvalue()
    if oversize:
        monkeypatch.setattr(gift_images, 'MAX_IMAGE_BYTES', len(raw) - 1)

    class Response:
        status = 200
        headers = {'Content-Type': 'image/png'}
        content = None
        async def __aenter__(self):
            self.content = self
            return self
        async def __aexit__(self, *args):
            pass
        async def iter_chunked(self, size):
            for start in range(0, len(raw), 7):
                yield raw[start:start + 7]

    class Session:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(gift_images.aiohttp, 'ClientSession', Session)
    if oversize:
        with pytest.raises(gift_images.GiftImageUnavailable):
            await gift_images.fetch_gift_image('https://t.me/nft/InputKey-25057')
    else:
        assert (await gift_images.fetch_gift_image('https://t.me/nft/InputKey-25057')).startswith(b'\xff\xd8\xff')
