# Approved implementation baseline (DEMO)

## Source reference observations

- Video length ~14.56 seconds, vertical 576×1248 recording.
- ~0–10 seconds: a purple native Telegram gift card from user Franklin, artwork for `Input Key #25057`, line «предлагает Вам 1 000 Stars», active countdown, buttons «Отклонить» / «Принять».
- ~11–13 seconds: a follow-up state «Подарок успешно продан», with «Передать» / «Как передать?» buttons.
- Attached screenshot: Telegram modal with numbered instructions.
- Native UI and its payment claims are **not** reproduced as a Telegram system operation; the project uses honest demo captions and regular Telegram buttons.

## Stack decision

| Component | Technology | Why |
|---|---|---|
| Runtime | Python 3.12 | Mature deployment/runtime |
| HTTP + Telegram Bot API | aiohttp + direct official HTTPS requests | No non-official MTProto methods; full control of new Business Bot API fields |
| Webhook | aiohttp web.Application | Public HTTPS webhook served by Railway domain; optional secret header |
| DB | Railway PostgreSQL | Persistent, transactional; row locks and SKIP LOCKED |
| Database mapper | SQLAlchemy 2 | Clear business models and transaction boundaries |
| Migrations | Alembic | Versioned schema |
| Validator | pydantic-settings | Single environment layer with startup validation |
| Scheduler | Dedicated async task + database queries | Crash-safe expiration, serialized in DB; no Redis requirement for v1 |
| Image processing | Pillow for bundled assets | Static fallback PNG |
| Deployment | Dockerfile + railway.json | Reproducible root deployment |

## Components

```text
Telegram webhook ---> aiohttp /telegram/webhook ---> AppHandler
                                                  |      |-- authenticated private bot menu
                                                  |      |-- persisted wizard (UserFlow)
                                                  |      |-- business connection/chat capture
                                                  |      |-- offer/recipient callback checks
                                                  |      |-- admin menus/actions
                                                  |-- Store / SQLAlchemy / PostgreSQL
                                                  |-- Telegram transport: official Bot API
                                                  `-- DemoTransferGateway (no NFT/Stars transfer)
expiration_worker ----> Postgres active & due offers ---> status + event ---> Telegram editMessageCaption
```

## Recipient selection and security

1. `TARGET_CHAT_ID` from Railway if set; must match a discovered private Business Chat.
2. Explicitly selected saved Business Chat in the creation wizard.
3. `TARGET_USER_ID` from Railway matched against discovered chat's user ID.
4. `TARGET_USERNAME`, only if an observed chat has that username.
5. Exactly one eligible observed Business Chat if no explicit target exists.

Reject ambiguous Business Connections and stale chats. A Telegram username alone is not a valid direct-message address. Both Business Connection and right `can_reply` must be active. A verified user callback is permitted without having started the bot, but only for the matching Offer recipient; blocked users cannot act.

## State machine

```text
Wizard: WAIT_URL -> WAIT_STARS -> WAIT_EXPIRATION -> WAIT_IMAGE -> WAIT_NAME
     -> WAIT_TARGET -> PREVIEW -> send/edit/cancel
Offer: draft -(confirmed Telegram send)-> active -(recipient accepts)-> accepted
             |                         |                           |
             |                         +- declined                 +- transfer_requested (DEMO)
             |                         +- expired
             |                         +- cancelled
             +- cancelled
```

`delivery_status` is separate (`sending`, `sent`, `failed`, `unknown`, `deleted`). `expires_at` is enforced in both the atomic callback transaction and periodic DB worker. For safe delivery uncertainty, no automatic duplicate sends. Captions are edited by the worker when possible.

## Next stage (not included)

A genuine Telegram Gift Offer or NFT/Stars transfer must use officially supported actor permissions and transactions, separate from the demo state machine. `app/services/transfer.py` defines a narrow request-validation port. It does not authenticate end-user MTProto sessions, collect credentials, or perform transactions. Additional service design and live API verification will be required before any real-money/NFT implementation.

## Business-chat quick-offer (v2)

An outgoing owner's `business_message` is parsed only when its entire text/caption contains three fields (NFT URL, positive Stars count, duration). Server authorizes creator against the active connection owner, DB whitelist, bot reply rights and recent incoming client message. The offer is bound to `msg.chat.id` and `msg.business_connection_id`, **ignoring the global Railway TARGET**, and saved with `source_message_id` for deduplication. It then attempts `sendPhoto` with a freshly downloaded photo of the NFT from the known Fragment CDN (`https://nft.fragment.com/gift/<slug-lower>.medium.jpg`) and the same callback state machine. If media download fails, it does not claim the offer was sent: the owner can instead attach their own photo with the three fields in the caption. The image fetch is from a fixed host, with MIME/size checks and Pillow verification. Data migrations: `0002_business_chat_commands`. Bot replies are visible to both chat participants, explicitly labeled DEMO.
