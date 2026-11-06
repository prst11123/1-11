"""Durable PostgreSQL expiration and message-sync worker."""
import asyncio
import logging
from .handlers import AppHandler
from .telegram import TelegramError

log=logging.getLogger(__name__)


async def expiration_worker(h: AppHandler):
    """Database-driven; safe on a single Railway replica. Row locking guards parallel interactions."""
    n=0
    while True:
        try:
            stale=await h.db("reconcile_sends",2)
            if stale:
                log.warning("uncertain_deliveries count=%s",stale)
            expired=await h.db("due_offers",50)
            if expired:
                log.info("offers_expired count=%s ids=%s",len(expired),expired,extra={"event":"OFFER_EXPIRED"})
            sync=await h.db("pending_sync",40)
            for o in sync:
                try:
                    await h.sync_offer(o)
                except Exception:
                    log.exception("offer_sync_unhandled offer_id=%s",o.id)
            n+=1
            if n % max(1,int(86400/h.cfg.expiration_sweep_seconds)) == 0:
                await h.db("prune_receipts",30)
                await h.db("prune_inline",14)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("expiration_worker_error")
        await asyncio.sleep(h.cfg.expiration_sweep_seconds)
