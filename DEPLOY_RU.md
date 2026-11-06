# Установка с нуля — Telegram Business NFT Gift DEMO V3

**Это демонстрационный бот.** В нём нет настоящего перевода NFT и Stars. Карточки оферов помечены DEMO.

## 1. Новый GitHub

1. Создай пустой репозиторий.
2. Распакуй ZIP и открой папку с проектом.
3. В корень GitHub-репозитория загрузи **содержимое папки**, а не сам ZIP и не лишнюю вложенную папку `telegram-gift-offers`.
4. Обязательно сохрани пути: `Dockerfile`, `railway.json`, `requirements.txt`, `alembic.ini`, `app/main.py`, `app/db.py`, `app/assets/fallback.png`, `alembic/versions/0001_initial.py`, `0002_business_chat_commands.py`, `0003_demo_contact_settings.py`.
5. После загрузки должна быть папка `app/`, а не `app/app/`. Коммитни все файлы.
6. Никогда не загружай `.env` с реальным токеном или паролем в GitHub. В репозитории лежит только `.env.example` с заглушками.

## 2. Новый Railway

1. Создай проект Railway и сервис из нового GitHub-репозитория.
2. Добавь в **тот же Railway-проект** базу данных PostgreSQL (`+ New` -> Database -> PostgreSQL).
3. Открой сервис бота -> **Settings -> Networking -> Generate Domain**. Порт `8080`.
4. Открой **Variables** сервиса бота, создай переменные по отдельному файлу `RAILWAY_VARIABLES_NEW_PROJECT.txt` (который скачан отдельно, НЕ загружай его в GitHub).
5. Заменить нужно `BOT_TOKEN`, `ADMIN_IDS`, `OWNER_IDS` и `WEBHOOK_URL` на настоящие значения.
6. `DATABASE_URL=${{Postgres.DATABASE_URL}}` — **точная ссылка** на сервис PostgreSQL; если сервис БД называется не `Postgres`, используй его точное имя в ссылке.
7. `WEBHOOK_URL` — только `https://публичный-домен`, без `/health` или `/telegram/webhook`. Путь вебхука бот добавит сам.
8. После внесения переменных нажми Apply/Deploy и дождись состояния Online.
9. Проверь `https://<твой-домен>/health`: ожидается `{"status":"ok"}`.

## 3. BotFather и Telegram Business

1. Получи BOT_TOKEN у BotFather (`/mybots` -> нужный бот -> API Token) или создай нового бота.
2. В BotFather включи поддержку подключения бота к Business-аккаунтам (Business Mode / Secretary Mode, название зависит от интерфейса).
3. В Telegram Business-аккаунта открой Настройки -> Telegram для бизнеса -> Чат-боты, выбери бота и разреши ответы от имени Business.
4. Убедись, что подключение разрешает обрабатывать нужные чаты; для ответа в чате учитываются Telegram Business ограничения.
5. Открой личный чат с ботом и отправь `/start`.

## 4. Проверка офера

В тестовой переписке Business-аккаунт отправляет сообщение из трёх строк:

```
https://t.me/nft/PlushPepe-123
1000
15м
```

Бот проверяет права и пытается отправить **DEMO**-карточку в тот же чат. Изображение берётся из публичного источника best-effort, без гарантий; если получить его не удалось, можно отправить фотографию с теми же тремя строками в подписи.

В личном чате бота доступна админ-панель, изменение `@username` для справок (только `OWNER_IDS`), а надпись «Бот от A/X T’eams» отображается **только в интерфейсе самого бота**, не в Business-оферах и не в инструкциях получателя.

## 5. Если упало

- `ModuleNotFoundError: No module named app.db` -> проверь `app/db.py` и остальные расширения `.py`.
- `DEFAULT_IMAGE_PATH` -> укажи `app/assets/fallback.png` и проверь, что файл загружен.
- Ошибка `DATABASE_URL` -> используй полную строку подключения `${{Postgres.DATABASE_URL}}`.
- Бот не отвечает -> проверь публичный домен, `WEBHOOK_URL`, `/health`, логи Railway и права Business.
- Для существующей БД удалять данные не требуется: Docker выполняет `python -m alembic upgrade head`.

Все ключи/секреты указываются **в Railway Variables**, а не в GitHub.
