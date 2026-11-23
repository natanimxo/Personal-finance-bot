"""Drive the real bot handlers against a fake Telegram Bot API (no network)."""
import asyncio
import json
import re

from telegram import Update
from telegram.request import BaseRequest

UID = 42
USER = {"id": UID, "is_bot": False, "first_name": "U"}
CHAT = {"id": UID, "type": "private"}
ALLOWED_TAGS = r"</?(b|i|u|s|code|pre|a)(\s[^>]*)?>"


def assert_valid_html(text: str):
    """Roughly what Telegram's HTML parser requires: only known tags, <>& escaped."""
    rest = re.sub(ALLOWED_TAGS, "", text)
    assert "<" not in rest and ">" not in rest, f"unescaped < or > in: {text!r}"
    for m in re.finditer("&", rest):
        assert re.match(r"&(lt|gt|amp|quot|#\d+);", rest[m.start():]), f"bare & in: {text!r}"


class FakeRequest(BaseRequest):
    def __init__(self, rate_limit: int = None):
        self.sent = []          # (endpoint, params) for every message-producing call
        self.member_status = "member"
        self.member_error = False      # getChatMember fails (Telegram trouble)
        self.member_checks = 0
        self.forbidden_chats = set()   # chats that blocked the bot
        self.rate_limit = rate_limit   # max sendMessage calls in any 1 s window, like Telegram
        self.too_many = 0              # 429s returned
        self._send_times = []
        self.delivered = []            # chat ids that really received a message
        self.calls = []                # every (endpoint, params), in order
        self.documents = []            # files sent with sendDocument
        self.files = {}                # file_id -> bytes, for files users send to the bot

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self):
        return 5

    async def do_request(self, url, method, request_data=None, **kwargs):
        if "/file/bot" in url:                       # downloading an uploaded file
            return 200, self.files[url.rsplit("/", 1)[1]]
        endpoint = url.rsplit("/", 1)[1]
        params = request_data.parameters if request_data else {}
        self.calls.append((endpoint, params))
        if endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Bot", "username": "bot"}
        elif endpoint == "getFile":
            file_id = params["file_id"]
            result = {"file_id": file_id, "file_unique_id": file_id, "file_size": len(self.files[file_id]),
                      "file_path": file_id}
        elif endpoint == "getChatMember":
            self.member_checks += 1
            if self.member_error:
                return 400, json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}).encode()
            result = {"status": self.member_status, "user": USER}
        elif endpoint == "sendMessage" and self.rate_limit is not None and self._over_limit():
            self.too_many += 1
            return 429, json.dumps({"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 1",
                                    "parameters": {"retry_after": 1}}).encode()
        elif endpoint == "sendMessage" and int(params.get("chat_id", 0)) in self.forbidden_chats:
            return 403, json.dumps({"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}).encode()
        elif endpoint == "sendDocument":
            self.sent.append((endpoint, params))
            files = (request_data.multipart_data or {}) if request_data else {}
            self.documents.extend(files.values())   # (filename, bytes, mimetype)
            result = {"message_id": len(self.sent), "date": 0, "chat": CHAT}
        elif endpoint in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            self.sent.append((endpoint, params))
            if endpoint == "sendMessage":
                self.delivered.append(int(params.get("chat_id", 0)))
            if "text" in params and params.get("parse_mode") == "HTML":
                assert_valid_html(params["text"])
            result = {"message_id": len(self.sent), "date": 0, "chat": CHAT, "text": params.get("text", "")}
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()


    def _over_limit(self):
        import time
        now = time.monotonic()
        self._send_times = [t for t in self._send_times if now - t < 1.0]
        if len(self._send_times) >= self.rate_limit:
            return True
        self._send_times.append(now)
        return False


class Harness:
    def __init__(self, flow_timeout=600, rate_limit=None):
        from app.main import build_application

        self.request = FakeRequest(rate_limit=rate_limit)
        self.app = build_application(request=self.request, flow_timeout=flow_timeout)
        self._n = 0

    async def __aenter__(self):
        await self.app.initialize()
        await self.app.start()
        return self

    async def __aexit__(self, *exc):
        await self.app.stop()
        await self.app.shutdown()

    def _next(self):
        self._n += 1
        return self._n

    async def text(self, text):
        n = self._next()
        message = {"message_id": 1000 + n, "date": 0, "chat": CHAT, "from": USER, "text": text}
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return await self._process({"update_id": n, "message": message})

    async def document(self, content: bytes, filename: str, caption: str = ""):
        """The user sends a file (with an optional caption)."""
        n = self._next()
        file_id = f"file{n}"
        self.request.files[file_id] = content
        message = {"message_id": 1000 + n, "date": 0, "chat": CHAT, "from": USER, "caption": caption,
                   "document": {"file_id": file_id, "file_unique_id": file_id, "file_name": filename,
                                "file_size": len(content)}}
        if caption.startswith("/"):
            message["caption_entities"] = [{"type": "bot_command", "offset": 0, "length": len(caption.split()[0])}]
        return await self._process({"update_id": n, "message": message})

    async def tap(self, data):
        n = self._next()
        return await self._process({"update_id": n, "callback_query": {
            "id": str(n), "from": USER, "chat_instance": "x", "data": data,
            "message": {"message_id": 1, "date": 0, "chat": CHAT, "text": "x",
                        "from": {"id": 1, "is_bot": True, "first_name": "Bot"}}}})

    async def _process(self, payload):
        self.request.sent.clear()
        await self.app.process_update(Update.de_json(payload, self.app.bot))
        return Sent(self.request.sent)


class Sent(list):
    @property
    def texts(self):
        return [p.get("text", "") for _, p in self]

    def markup(self, i=-1):
        markup = self[i][1].get("reply_markup")
        return json.loads(markup) if isinstance(markup, str) else (markup or {})

    def buttons(self, i=-1):
        m = self.markup(i)
        rows = m.get("inline_keyboard") or m.get("keyboard") or []
        return [b if isinstance(b, dict) else {"text": b} for row in rows for b in row]

    def has_main_keyboard(self, i=-1):
        return any(b["text"] == "➕ Add Expense" for b in self.buttons(i))


def run(coro):
    return asyncio.run(coro)
