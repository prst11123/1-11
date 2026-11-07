"""Telegram inline/reply keyboards; callback data always under 64 bytes."""

def btn(text: str, data: str=None, url: str=None):
    d={"text":text}
    if data is not None:d["callback_data"]=data
    if url is not None:d["url"]=url
    return d


def inline(*rows):
    return {"inline_keyboard":[list(r) for r in rows]}


def main_menu(admin=False):
    # A test and an inline share need no Business connection or known recipient.
    keyboard=[
        [{"text":"🧪 Тест офера"}, {"text":"📤 В любой чат"}],
        [{"text":"📋 Мои оферы"}, {"text":"💼 Business подключения"}],
        [{"text":"📊 Статистика"}, {"text":"❓ FAQ"}],
    ]
    if admin:
        keyboard.append([{"text":"🔧 Диагностика"}, {"text":"⚙️ Админ-панель"}])
    return {"keyboard":keyboard, "resize_keyboard":True, "is_persistent":True}


def cancel_keyboard():
    return inline([btn("❌ Отмена", "flow:cancel")])


def preview_keyboard():
    return inline([btn("✅ Отправить", "flow:send")], [btn("✏️ Изменить", "flow:edit"), btn("❌ Отмена", "flow:cancel")])


def edit_keyboard():
    return inline([btn("🔗 Ссылка", "flow:edit:url"), btn("⭐ Stars", "flow:edit:stars")],
                  [btn("⏱ Время", "flow:edit:duration"), btn("🖼 Изображение", "flow:edit:image")],
                  [btn("🏷 Название", "flow:edit:name"), btn("🎯 Target", "flow:edit:target")],
                  [btn("↩️ Preview", "flow:preview")])


def duration_keyboard():
    return inline([btn("5 мин", "flow:duration:5"), btn("10 мин", "flow:duration:10"), btn("15 мин", "flow:duration:15")],
                  [btn("30 мин", "flow:duration:30"), btn("1 час", "flow:duration:60")],
                  [btn("❌ Отмена", "flow:cancel")])


def target_keyboard(rows, page=0, total=0):
    buttons=[]
    for c,b,enabled in rows:
        name=c.first_name or c.username or str(c.chat_id)
        label=f"{'🟢' if enabled else '🔴'} {name[:20]} · {c.chat_id}"
        buttons.append([btn(label, f"flow:target:{c.id}")])
    nav=[]
    if page:nav.append(btn("◀️", f"flow:targets:{page-1}"))
    if (page+1)*8 < total:nav.append(btn("▶️", f"flow:targets:{page+1}"))
    if nav:buttons.append(nav)
    buttons.append([btn("🎯 Railway / автоматический", "flow:target:auto")])
    buttons.append([btn("❌ Отмена", "flow:cancel")])
    return {"inline_keyboard":buttons}


def offer_keyboard(o, contact_username: str | None = None):
    rows=[[btn("🔎 Показать подарок",url=o.gift_url)]]
    if o.status == "active":
        rows.append([btn("✕ Отклонить",f"offer:decline:{o.id}"),btn("✓ Принять",f"offer:accept:{o.id}")])
    elif o.status == "accepted":
        rows.append([btn("ℹ️ Что означает DEMO?",f"offer:instructions:{o.id}")])
        if contact_username:
            rows.append([btn("🆘 Поддержка",url=f"https://t.me/{contact_username}")])
    return inline(*rows)


def admin_keyboard():
    return inline([btn("📊 Статистика", "admin:stats"),btn("👥 Пользователи", "admin:users:0")],
                  [btn("➕ Добавить пользователя", "admin:input:allow"),btn("🚫 Убрать доступ", "admin:input:revoke")],
                  [btn("⛔ Заблокировать", "admin:input:block"),btn("✅ Разблокировать", "admin:input:unblock")],
                  [btn("🛡 Администраторы", "admin:admins")],
                  [btn("💼 Business Connections", "admin:business"),btn("🎁 Offers", "admin:offers:0")],
                  [btn("🎯 Текущий получатель", "admin:target")],
                  [btn("✏️ FAQ", "admin:faq"), btn("👤 Контакт поддержки", "admin:contact")],
                  [btn("🧾 Логи", "admin:logs:0"),btn("📑 Admin Audit", "admin:audit:0")],
                  [btn("↩️ Назад", "admin:home")])


def user_actions(user_id, is_owner=False):
    rows=[[btn("✅ Разрешить",f"admin:useract:allow:{user_id}"),btn("❌ Запретить",f"admin:useract:revoke:{user_id}")],
          [btn("⛔ Блок",f"admin:useract:block:{user_id}"),btn("🔓 Разблок",f"admin:useract:unblock:{user_id}")],
          [btn("⬆️ Сделать Admin",f"admin:useract:promote:{user_id}"),btn("⬇️ Убрать Admin",f"admin:useract:demote:{user_id}")],
          [btn("↩️ Пользователи", "admin:users:0")]]
    return {"inline_keyboard":rows}


def page_keyboard(prefix: str, page: int, total: int, extra=None):
    row=[]
    if page:row.append(btn("◀️",f"{prefix}:{page-1}"))
    if (page+1)*8 < total:row.append(btn("▶️",f"{prefix}:{page+1}"))
    buttons=[row] if row else []
    if extra:buttons.extend(extra)
    buttons.append([btn("↩️ Админ-панель","admin:panel")])
    return {"inline_keyboard":buttons}


def test_offer_keyboard(status: str = "active", contact_username: str | None = None):
    rows=[[btn("🔎 Пример NFT", url="https://t.me/nft/Example-1")],
          [{"text":"📤 Отправить DEMO в другой чат", "switch_inline_query":""}]]
    if status == "active":
        rows.append([btn("✕ Отклонить", "test:decline"), btn("✓ Принять", "test:accept")])
    elif status == "accepted":
        rows.append([btn("ℹ️ Что означает DEMO?", "test:instructions")])
        if contact_username:
            rows.append([btn("🆘 Поддержка",url=f"https://t.me/{contact_username}")])
    return inline(*rows)


def inline_offer_keyboard(offer_id: int, gift_url: str, status: str, media: str,
                          contact_username: str | None = None):
    # Inline messages carry no business_connection_id; callbacks resolve a
    # database template and a per-inline-message state.
    rows=[[btn("🔎 Показать подарок", url=gift_url)]]
    if status == "active":
        rows.append([btn("✕ Отклонить", f"inline:decline:{offer_id}:{media}"),
                     btn("✓ Принять", f"inline:accept:{offer_id}:{media}")])
    elif status == "accepted":
        rows.append([btn("ℹ️ Что означает DEMO?", f"inline:instructions:{offer_id}:{media}")])
        if contact_username:
            rows.append([btn("🆘 Поддержка",url=f"https://t.me/{contact_username}")])
    return inline(*rows)
