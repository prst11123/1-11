# Telegram Business · NFT Gift Offer (DEMO) — V3

Telegram Business webhook bot with **real delivery of demo NFT Gift Offer messages** into eligible, previously observed private Business chats. Python 3.12, aiohttp, PostgreSQL, SQLAlchemy, Alembic, Docker, Railway. Russian-language Telegram interface; persistent wizard, roles, audit trail, expiration worker.


**Новая установка:** см. [DEPLOY_RU.md](DEPLOY_RU.md). В версии V3 можно изменить username для справок через админ-панель; подпись «Бот от A/X T’eams» отображается только в личных сообщениях бота, не в оферах.

> **DEMO, not a Telegram escrow / payment / native Gift Offer.** No Stars are charged, reserved, issued or credited. No NFT is transferred. The sender and recipient see an explicit `DEMO` label. This bot never asks a recipient to send a gift to an unrelated account in exchange for a promised payout.

## Быстрое создание прямо в Business-чате (новый режим)

**Владелец подключённого Business-аккаунта** отправляет человеку одно сообщение ровно из трёх значений (можно с `/offer` в начале):

```text
https://t.me/nft/PlushPepe-123
1000
15м
```

Это означает **ссылка на конкретный NFT → количество Stars → длительность**. Другие варианты:
`/offer https://t.me/nft/InputKey-25057 2500 30`, `https://t.me/nft/PlushPepe-123 1000 1ч`.
Время можно указывать в минутах (`15`, `15м`, `15мин`), часах (`1ч`, `2h`); допустимый срок — 1–10 080 минут.

1. Получатель **предварительно должен написать** Business-владельцу в этом чате в последние 24 часа; боту нужно `can_reply` и доступ к этому чату.
2. Telegram присылает `business_message` исходящего сообщения владельца. Бот распознаёт три поля и проверяет разрешения; **сообщения получателя никогда не запускают создание Offer**.
3. Бот пытается получить фотографию подарка по его точному slug из публичного CDN `nft.fragment.com`, конвертирует её в JPEG и отправляет через официальный `sendPhoto` с `business_connection_id` **в тот же чат** (а не в Railway Target). В карточке чётко написано `DEMO`; платежей и NFT-переводов нет.
4. Если CDN не возвращает изображение, **чужая картинка не подставляется**. Владелец получает сообщение об ошибке в приватном чате с ботом. Для повторной отправки можно приложить фотографию нужного NFT **к тому же трёхстрочному тексту в подписи к фото**; также допускается изображение-документ (в этом случае отправляется документ).
5. Действия, события, статистика и истечение срока работают так же, как у предложений, созданных из меню. Повторное получение того же `business_message` не отправляет ещё одну карточку.

**Важно:** Telegram Bot API не содержит универсального метода извлечения изображения конкретного NFT по ссылке. Публичный CDN `nft.fragment.com` — best-effort, не гарантия. Нативный системный Telegram Gift Offer здесь не создаётся. Встроенный мастер `/create` остаётся доступен. Railway `TARGET_CHAT_ID` не переопределяет чат, в котором вручную отправлена трёхстрочная команда.

### Обновление предыдущей версии

Замените изменённые файлы в GitHub **с сохранением путей**, включая `app/quick_offer.py`, `app/gift_images.py` и `alembic/versions/0002_business_chat_commands.py`. При запуске Docker автоматически выполнит `alembic upgrade head`, добавив поле `offers.source_message_id` и уникальный индекс. **Не удаляйте PostgreSQL и не пересоздавайте БД**; старые оферы сохраняются. Railway Variables менять не требуется. Для GitHub удобнее GitHub Desktop; веб-загрузка отдельных файлов иногда теряет исходные пути или расширения `.py`.

## What is reproduced from the supplied video

The example video contains an `Input Key #25057` offer for `1 000 Stars`. Its initial card has `Отклонить` and `Принять`. After acceptance, the interface shows `Передать` and `Как передать?`, with an instruction popup. This project implements **the same two-step interaction** using regular Telegram messages: a photo/document with an HTML caption and an inline keyboard; accepting changes the message caption and keyboard. `Как передать?` sends a separate configurable explanation, or displays a Telegram alert if replying is no longer available. The red NFT artwork from the supplied video is available as **`app/assets/sample-input-key.png`**; the safe generic fallback is `app/assets/fallback.png`.

Telegram **does not allow** a bot to clone the purple `Telegram`-branded native gift card, alter the Telegram client UI, or represent a `sendPhoto` message as an actual on-chain/native Gift Offer. Button colors, modal appearance, native card frames and typography are controlled by Telegram clients, not this code. The project does not imitate the video's misleading claim that Stars have already been paid.

## Features

- Real Bot API webhook secured by `X-Telegram-Bot-Api-Secret-Token`; `GET /health` checks PostgreSQL.
- `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`; `getBusinessConnection` before sending.
- Owners, admins, whitelist and blocklist. Recipient can use buttons **without ever sending `/start`** to the bot.
- One-message creation in an existing authorized Business chat: NFT link + Stars + duration → NFT-specific photo/card sent to that same chat.
- Persistent guided creation: URL → Stars → duration → image or fallback → name → target → preview → send/edit/cancel.
- Target via Railway variables or discovered Business Chat, with strict server-side permissions and last inbound-message window.
- Actual **`sendPhoto`** or **`sendDocument`** request with `business_connection_id`; `message_id` persisted after confirmed API response.
- Offer states `draft → active → accepted → transfer_requested`; `active → declined/expired/cancelled`.
- `Принять`, `Отклонить`, `Передать (DEMO)`, `Как передать?`, `Показать подарок` (NFT URL), full handlers.
- Expiration sweeper every 20 seconds by default; atomic Postgres row locking, no in-memory timers required.
- History, `offer_events`, `admin_audit_log`, per-user and global statistics; admin UI in Telegram with pagination.
- Images as Telegram photo `file_id`, image document `file_id`, or local bundled fallback.
- Separate `TransferGateway` and `DemoTransferGateway`: future official transaction module can be integrated at a service boundary, not by inserting code into callbacks.
- Request validation, dedupe, idempotent state transitions, error reporting, retry only for confirmed failed sends.

## Requirements

- A Telegram bot created through [@BotFather](https://t.me/BotFather) with Business Mode enabled.
- A Telegram account eligible to connect a Business chatbot (Business availability and Premium conditions depend on Telegram).
- The connected Business account must authorize the bot to respond in the appropriate private chats (`rights.can_reply`).
- The recipient must have sent a message to the Business account **within the preceding 24 hours**, and the bot must have received/observed the chat while connected. A user ID alone is **not** sufficient for delivery.
- A Railway project with GitHub deployment, one service for the app and one PostgreSQL database.

## Deployment: GitHub → Railway → PostgreSQL → Variables → Deploy

1. Create your bot with `/newbot` in BotFather. Keep `BOT_TOKEN` secret. Enable Business Mode in the bot settings.
2. Upload the **contents of this project** (the `Dockerfile`, `app/`, `alembic/`, `requirements.txt`, etc.) to the **root of a GitHub repository**. Do not commit `.env`, real secrets, or DB dumps.
3. In Railway create a project, connect the GitHub repo as a service, and add a Railway **PostgreSQL** database. The Dockerfile in the project root is detected automatically.
4. In your application service, open Settings → Networking and generate a public Railway domain (e.g. `https://your-service.up.railway.app`). Set `WEBHOOK_URL` to the base domain **without** `/telegram/webhook`.
5. Add Railway Variables from the table below. `DATABASE_URL` can reference `${{Postgres.DATABASE_URL}}` (adjust `Postgres` if the service has another name). Set `ADMIN_IDS` and `OWNER_IDS` to your numeric Telegram IDs. Generate a random `WEBHOOK_SECRET` with at least 24 alphanumeric/underscore/hyphen characters (e.g., `python -c "import secrets; print(secrets.token_urlsafe(36))"`).
6. Set exactly **one app replica**, and do not enable serverless sleep. Disable any Railway cron schedule for this service: it is a long-running webhook server and expiration worker. Use a plan/resource allocation that supports continuous processes.
7. Railway will build the Dockerfile, run `alembic upgrade head`, and start `python -m app.main`. Wait for `/health` to return `{"status":"ok"}`. The server binds `0.0.0.0:$PORT`.
8. Open your bot privately and send `/start` and `/admin`. The initial owners/admins in Railway Variables receive access during startup.
9. In the Telegram account that will be used as the Business sender, go to Telegram Business → Chatbots / Business Bots, connect your bot and authorize replying to relevant chats. The UI wording depends on the Telegram client version.
10. Ask the intended recipient to send a message to that Business account. Check **Business подключения** in the bot. A recent private Business Chat and active `can_reply` are required.
11. If using a fixed recipient, enter its numeric ID in `TARGET_CHAT_ID` or `TARGET_USER_ID`, then redeploy. Open **Админ-панель → Текущий получатель** to verify the resolved Business Connection and current availability.
12. Select **Создать офер**, enter the NFT URL, Stars, lifetime and image/name, verify preview/Target and choose **Отправить**. Telegram API is called directly for the Business Chat; the bot reports the resulting Telegram message ID.

### Important about Railway Variables changes

Change `TARGET_CHAT_ID` or `TARGET_USER_ID` in the **app service** and deploy/redeploy the new variable set. The new process reads them through `app/config.py`; code/GitHub changes are unnecessary. A fixed target is usable only if a matching recent Business Chat is already known for an active connection with `can_reply` permission. Variables **do not bypass Telegram restrictions**. Existing Offers keep their original recipient and Business Connection.

### Variables

| Variable | Required | Meaning / sample |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | BotFather API token; keep secret |
| `DATABASE_URL` | Yes | Railway PostgreSQL URL; supports `postgres://`, `postgresql://`, `postgresql+psycopg://` |
| `ADMIN_IDS` | Yes | Comma-separated numeric Telegram IDs, e.g. `123456789,987654321` |
| `OWNER_IDS` | Optional | Comma-separated owner IDs **included in** `ADMIN_IDS`; if omitted, lowest ADMIN_ID becomes the owner |
| `WEBHOOK_URL` | Yes | `https://your-app.up.railway.app` (base URL, no path) |
| `WEBHOOK_SECRET` | Yes | Random 24–256 char `A-Z a-z 0-9 _ -` token used for Telegram webhook header |
| `TARGET_CHAT_ID` | Optional | Numeric **known private Business Chat ID**, highest target priority |
| `TARGET_USER_ID` | Optional | Numeric recipient user ID; resolves to a **known Business Chat**, not direct Bot chat |
| `TARGET_USERNAME` | Optional | Username of previously observed chat, last-resort hint; not guaranteed delivery |
| `PORT` | Optional | Railway injected port, defaults to `8080` locally |
| `LOG_LEVEL` | Optional | `INFO`, `WARNING`, `DEBUG`, etc. (no credentials printed) |
| `DEFAULT_STARS` | Optional | Used when entering `Авто` at the Stars step (`1000` by default) |
| `DEFAULT_EXPIRATION` | Optional | Used when entering `Авто` at the duration step (minutes, default `30`) |
| `DEFAULT_GIFT_URL` | Optional | Used when user enters `Авто` at the URL step |
| `DEFAULT_GIFT_NAME` | Optional | Used when user enters `Авто` for name and selected the default URL |
| `DEFAULT_IMAGE_PATH` | Optional | Default `app/assets/fallback.png`; `app/assets/sample-input-key.png` reproduces artwork from sample video |
| `EXPIRATION_SWEEP_SECONDS` | Optional | DB worker frequency, default `20` (5–300) |

The `DEFAULT_IMAGE_PATH` variable must refer to a bundled image in `app/assets/`; changing to another path already included in the repo requires **only a Railway variable update**. To upload a new asset, that asset must first be added to the repository or uploaded through the bot during creation.

## Main menu, user and admin workflows

**User**: `/start` → `Создать офер` → NFT URL (`https://t.me/nft/...`) → positive integer Stars → 1–10 080 minutes → photo / image document / `Пропустить` → name / `Авто` → Business Target (explicit saved chat or automatic Railway target) → image preview → `Отправить` / `Изменить` / `Отмена`. `/cancel` works during the wizard. The flow is saved in PostgreSQL and survives process restarts. `Мои оферы` shows status and supports cancellation of active Offers and explicit retry of **confirmed** failed deliveries.

**Business**: Telegram delivers a `business_connection` update; it is stored with owner, rights, status and timestamp. Each inbound `business_message` from an individual recipient updates the observed chat, user ID and last inbound timestamp. Before send: confirm exact connection via `getBusinessConnection`, check its `can_reply`, restrict target to observed private chats, verify the 24-hour window, and send photo/document with `business_connection_id` to the observed `chat_id`. Replies / buttons are handled on behalf of the connected account.

**Offer**: `draft` (creation) → `sending` (delivery status) → Telegram `sendPhoto` / `sendDocument` → `active` plus `telegram_message_id` and `OFFER_SENT`. Callback `Принять` → `accepted`; then `Передать (DEMO)` → `transfer_requested` (no external movement). `Отклонить` → `declined`. `Как передать?` adds `INSTRUCTION_OPENED` and sends template text. Worker or interaction turns past-due active offers into `expired` and updates captions/markups. All actions have server checks and atomic rows locks.

**Admin**: `/admin` → global statistics, user list, allow/revoke/block/unblock, admin promotion/demotion (owner only), Business Connections, all Offers, Target configuration/status, event log and audit log. Owners are seeded through `OWNER_IDS`; configured administrators cannot be removed through the chat while they remain in `ADMIN_IDS`. Admins cannot demote/remove the owner or configured admins. Recipient clicks do **not** require whitelist, but are limited to the exact intended recipient and blocked users are rejected.

## Database and durability

Alembic revision `0001_initial` manages the baseline; `0002_business_chat_commands` adds a nullable Business source message ID and uniqueness constraint for quick-offer deduplication:

- `users` — identity, role (`user`, `admin`, `owner`), whitelist/blocklist, timestamps;
- `business_connections` — connection ID, owner, enabled flag, permissions, timestamps;
- `business_chats` — (connection ID, chat ID), incoming timestamp and observed recipient;
- `recipients` — future multi-recipient profile support;
- `offers` — gift URL, name, Telegram `file_id`, `stars_amount`, state, delivery status, message ID, expiration, action timestamps and version;
- `offer_events` — append-only event stream with actor/target/offer/connection/metadata;
- `admin_audit_log` — privileged permission actions;
- `user_flows` — persistent wizard state and draft data;
- `processed_updates`, `callback_receipts` — deduplication.

Every timestamp is written in UTC. The scheduler queries the database; there are no state-critical timers kept only in RAM. The state machine uses `SELECT ... FOR UPDATE` to serialize conflicting callbacks; the worker uses `SKIP LOCKED` on PostgreSQL. Two clicks cannot double-accept a single offer.

**Delivery outcomes:** `pending`, `sending`, `sent`, `failed`, `unknown`, `deleted`. A definite Telegram rejection is `failed`; admin/creator may explicitly retry if the reply window is still open. A network timeout or a crash after the remote API call may mean the message was actually sent: the outcome becomes `unknown` and the service **does not automatically send again**, to avoid duplicates. The sent status is recorded only after a successful Telegram API result has been persisted. A remote success followed by a database failure cannot be guaranteed exactly-once, because Bot API does not support an outgoing idempotency key; inspect the chat and logs before manual reconciliation.

## Security and scope

- All user/admin/recipient checks are on the server. Callback data is only an entity/action reference, never authorization.
- Both `recipient_user_id` and source Telegram `chat_id/message_id` are validated before callback actions. An Offer may only be accepted/declined by its intended recipient.
- `ADMIN_IDS` and `OWNER_IDS` are bootstrap-authorized; owner promotion is not permitted through the chat.
- The webhook uses a separate secret header, in addition to HTTPS.
- `DEFAULT_IMAGE_PATH` is restricted to bundled assets. URL validation accepts only `https://t.me/nft/<identifier>`; name and URLs are HTML escaped.
- The project intentionally does not contain code to perform real transfer, stars charging, wallets, private-key handling or unofficial Telegram account automation.
- The bot is for authorized interactions with existing Business chats, not unsolicited bulk messaging. Keep the single target explicit and check consent before sending.
- Source code and Docker image contain **no** actual tokens or passwords. `.gitignore` excludes `.env` and database files.

## Local development and checks

For a local deployment with a public HTTPS tunnel (Telegram cannot call localhost directly):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set real BOT_TOKEN, DATABASE_URL, ADMIN_IDS, WEBHOOK_URL, WEBHOOK_SECRET
alembic upgrade head
python -m app.main
```

For tests, use the development dependency manifest:

```bash
pip install -r requirements-dev.txt
python -m compileall -q app alembic tests
pytest -q
```

The tests use SQLite for deterministic local logic and mocks for Telegram; production uses PostgreSQL. Tests include parsing and validation, role/owner protection, callback idempotence, target permissions and freshness, state transitions, persistence of expiration, and a complete fake Business flow from incoming chat to simulated transfer. Migrations can also be verified on a local SQLite DB. **Neither unit tests nor SQLite prove Railway deployment or live Telegram Business delivery**; verify those with a valid bot and Business Connection on Railway.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Build Failed | Confirm `Dockerfile` exists with uppercase `D` and `requirements.txt` is at repository root; review Railway build logs |
| `COPY failed` | Set Railway Root Directory to the folder actually containing `Dockerfile`, `app/` and `alembic/`; don't reference absent files |
| Missing dependency | Check pip output and compatible Python 3.12 image; dependencies are in `requirements.txt` |
| Container crash on startup | Examine Railway logs for `CONFIG ERROR`, `alembic upgrade`, invalid token or DB unavailable |
| Bad `DATABASE_URL` | Use `${{Postgres.DATABASE_URL}}` from the Railway Postgres service; never use your local `localhost` database URL |
| Database unavailable | Check service, reference variable, Railway private network and migration logs |
| Invalid BOT_TOKEN | Copy token from BotFather; rotate a leaked token immediately |
| HTTP 409 conflict | Another process may be using the token with long polling / a competing webhook. Stop the other app and configure only one deployment |
| Bot deployed but silent | Check public HTTPS domain, `WEBHOOK_URL`, Railway `/health`, Telegram `setWebhook`, bot `/start`, admin whitelist and webhook secret |
| `/start` says no access | Add your Telegram ID to `ADMIN_IDS` or grant through admin panel |
| No Business Connection | Enable Business Mode in BotFather, connect bot in Telegram Business and grant relevant permissions |
| Missing Business Chats | The bot only knows chats observed through Business updates; the recipient should message the connected business account |
| `Target unavailable` | Ensure correct `TARGET_CHAT_ID`/`TARGET_USER_ID`, a recent inbound private chat and connection `rights.can_reply=true` |
| Offer stuck `unknown` | Check the real chat; a timeout/crash may have happened after successful send. Do not blindly resend |
| Offer sent but status text old | The caption edit may fail after deletion/permission loss; check Railway logs and `OFFER_MESSAGE_SYNC_FAILED` |
| Expired offer still displays active caption | Actions are blocked atomically in DB. Caption update is best effort; requires Telegram edit permission |
| Buttons appear but recipient doesn't use `/start` | Expected. The recipient can use Offer callbacks in their Business Chat without ever opening the bot |
| Changing Target has no effect | Apply Railway Variables and redeploy; existing Offers keep their previous target; only new Offers use the new environment |
| Telegram limitations | `TARGET_USERNAME` is not direct-addressable for a private person, and native NFT Gift Offer cards cannot be reproduced using Bot API |

## Official references

- [Telegram Bot API](https://core.telegram.org/bots/api): BusinessConnection, BusinessBotRights, getBusinessConnection, sendPhoto, sendDocument, editMessageCaption, answerCallbackQuery, setWebhook.
- [Telegram Gifts API](https://core.telegram.org/api/gifts): native gift methods are separate from demo Bot API messages.
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles).
- [Railway PostgreSQL](https://docs.railway.com/databases/postgresql).
- [Railway deployment healthchecks](https://docs.railway.com/deployments/healthchecks).

### Boundaries of version 1

No Telegram API call will create a native gift exchange, move an NFT or charge/credit Stars. The custom `TransferGateway` port is deliberately wired to the complete DEMO implementation. Integrating real official transactions requires a separate design/security review, Telegram-supported authorization, verification of ownership/offer terms, and explicit opt-in; it **cannot** be enabled by a variable on the current build.
