"""GET /healthz: 200 when the database answers, 503 when it doesn't.

A tiny asyncio HTTP server on $PORT, running in the bot's event loop. Phase 3
replaces it with the FastAPI app, which serves the same path.
"""
import asyncio
import json
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


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        request_line = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin-1")
        # Drain the headers; the body (if any) is ignored.
        while (await asyncio.wait_for(reader.readline(), timeout=5)) not in (b"\r\n", b"\n", b""):
            pass
        parts = request_line.split()
        if len(parts) >= 2 and parts[0] in ("GET", "HEAD") and parts[1].split("?")[0] == "/healthz":
            status, body = await health_status()
        else:
            status, body = 404, {"ok": False, "error": "not found"}
        payload = json.dumps(body).encode()
        reason = {200: "OK", 404: "Not Found", 503: "Service Unavailable"}[status]
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + (payload if parts and parts[0] != "HEAD" else b"")
        )
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def start_health_server(port: int, host: str = "0.0.0.0") -> asyncio.base_events.Server:
    server = await asyncio.start_server(_handle, host, port)
    logger.info("Health check listening on %s:%s/healthz", host, port)
    return server
