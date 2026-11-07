from types import SimpleNamespace
from datetime import timedelta
from app import keyboards as kb
from app.render import offer_caption, instructions
from app.states import utcnow


def offer(status="active"):
    return SimpleNamespace(id=4,gift_name="Input Key #25057",gift_url="https://t.me/nft/InputKey-25057",
                           stars_amount=1000,expires_at=utcnow()+timedelta(minutes=30),status=status)


def test_two_stage_buttons():
    active=kb.offer_keyboard(offer())
    assert any(b.get("callback_data")=="offer:accept:4" for row in active["inline_keyboard"] for b in row)
    assert not any("transfer" in b.get("callback_data","") for row in active["inline_keyboard"] for b in row)
    accepted=kb.offer_keyboard(offer("accepted"))
    assert not any(b.get("callback_data")=="offer:transfer:4" for row in accepted["inline_keyboard"] for b in row)
    assert any(b.get("callback_data")=="offer:instructions:4" for row in accepted["inline_keyboard"] for b in row)
    assert len(kb.offer_keyboard(offer("declined"))["inline_keyboard"])==1


def test_demo_disclaimer():
    assert "DEMO" in offer_caption(offer())
    assert "Stars не списаны" in offer_caption(offer("accepted"))
    assert "незнакомым аккаунтам" in instructions("ru")
