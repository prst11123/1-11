"""Railway HTTP webhook entrypoint with healthcheck and durable worker."""
from __future__ import annotations
import asyncio
import hmac
import json
import logging
import sys
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import text as sqltext
from pydantic import ValidationError
from .config import Settings
from .db import Database
from .store import Store
from .handlers import AppHandler
from .telegram import Telegram, TelegramError
from .worker import expiration_worker

log=logging.getLogger(__name__)
CONFIG_KEY=web.AppKey("config",Settings)
STORE_KEY=web.AppKey("store",Store)
TELEGRAM_KEY=web.AppKey("telegram",Telegram)
HANDLER_KEY=web.AppKey("handler",AppHandler)
READY_KEY=web.AppKey("ready",bool)
TASK_KEY=web.AppKey("expiration_task",asyncio.Task)


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        entry={
            "timestamp":datetime.now(timezone.utc).isoformat(),
            "level":record.levelname,
            "module":record.name,
            "event":getattr(record,"event",record.getMessage().split(" ",1)[0]),
            "user_id":getattr(record,"user_id",None),
            "offer_id":getattr(record,"offer_id",None),
            "business_connection_id":getattr(record,"business_connection_id",None),
            "message":record.getMessage(),
            "exception":self.formatException(record.exc_info) if record.exc_info else None,
        }
        return json.dumps(entry,ensure_ascii=False,default=str)


def configure_logging(level):
    h=logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonLogFormatter())
    root=logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    root.setLevel(getattr(logging,level.upper(),logging.INFO))
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def health(request):
    h=request.app[HANDLER_KEY]
    if not request.app.get(READY_KEY):
        return web.json_response({"status":"starting"},status=503)
    try:
        await asyncio.to_thread(check_database,h.store.db)
    except Exception:
        log.exception("health_database_unavailable")
        return web.json_response({"status":"database_unavailable"},status=503)
    return web.json_response({"status":"ok"})


def check_database(db):
    with db.engine.connect() as conn:
        conn.execute(sqltext("SELECT 1"))


async def webhook(request):
    app=request.app
    if not app.get(READY_KEY):
        raise web.HTTPServiceUnavailable()
    provided=request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(provided,app[CONFIG_KEY].webhook_secret):
        raise web.HTTPForbidden()
    try:
        body=await request.json()
    except (json.JSONDecodeError,ValueError):
        raise web.HTTPBadRequest()
    if not isinstance(body,dict):
        raise web.HTTPBadRequest()
    try:
        await app[HANDLER_KEY].dispatch(body)
    except Exception:
        log.exception("telegram_update_handler_failed")
        raise web.HTTPInternalServerError()
    return web.json_response({"ok":True})


async def startup(app):
    cfg=app[CONFIG_KEY]
    tg=app[TELEGRAM_KEY]
    try:
        await asyncio.to_thread(app[STORE_KEY].initialize_admins)
        await tg.start()
        me=await tg.api("getMe")
        log.info("telegram_authorized bot_id=%s username=%s",me.get("id"),me.get("username"))
        await tg.set_webhook(cfg.webhook_endpoint,cfg.webhook_secret)
        app[READY_KEY]=True
        app[TASK_KEY]=asyncio.create_task(expiration_worker(app[HANDLER_KEY]))
        log.info("service_ready webhook_path=/telegram/webhook port=%s",cfg.port)
    except Exception:
        log.exception("service_startup_failed")
        await tg.close()
        raise


async def cleanup(app):
    app[READY_KEY]=False
    task=app.get(TASK_KEY)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
    await app[TELEGRAM_KEY].close()
    await asyncio.to_thread(app[STORE_KEY].db.close)


def make_app(cfg:Settings):
    db=Database(cfg.database_url)
    store=Store(db,cfg)
    tg=Telegram(cfg.bot_token,cfg.default_image_path)
    handler=AppHandler(cfg,store,tg)
    app=web.Application(client_max_size=2*1024**2)
    app[CONFIG_KEY],app[STORE_KEY],app[TELEGRAM_KEY],app[HANDLER_KEY] = cfg,store,tg,handler
    app[READY_KEY]=False
    app.router.add_get("/health",health)
    app.router.add_post("/telegram/webhook",webhook)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def main():
    try:
        cfg=Settings()
    except ValidationError as exc:
        # Never print input values: they can contain BOT_TOKEN, DATABASE_URL credentials or secrets.
        for err in exc.errors(include_input=False,include_url=False):
            print(f"CONFIG ERROR: {'.'.join(map(str,err['loc']))}: {err['msg']}",file=sys.stderr)
        raise SystemExit(2)
    configure_logging(cfg.log_level)
    web.run_app(make_app(cfg),host="0.0.0.0",port=cfg.port,access_log=None)


if __name__=="__main__":
    main()
