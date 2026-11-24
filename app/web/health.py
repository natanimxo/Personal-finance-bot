"""GET /healthz: 200 when the database answers, 503 when it doesn't."""
import asyncio
import logging

from app.db import db_call, ping

logger = logging.getLogger(__name__)


async def health_status():
    try:
        ok = await asyncio.wait_for(db_call(ping), timeout=5)
    except Exception as e:
        logger.warning(f"Health check: database did not answer: {e}")
        ok = False
    return (200, {"ok": True, "db": "ok"}) if ok else (503, {"ok": False, "db": "error"})
