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


def member_payload(status: str, is_member: bool, user: dict) -> dict:
    """A ChatMember as Telegram sends it, with the fields each status requires."""
    p = {"status": status, "user": user}
    if status == "creator":
        p.update(is_anonymous=False)
    elif status == "administrator":
        p.update({k: True for k in ("can_be_edited", "is_anonymous", "can_manage_chat", "can_delete_messages",
                                    "can_manage_video_chats", "can_restrict_members", "can_promote_members",
                                    "can_change_info", "can_invite_users", "can_post_stories", "can_edit_stories",
                                    "can_delete_stories")})
    elif status == "restricted":
        p.update({k: False for k in ("can_change_info", "can_invite_users", "can_pin_messages", "can_send_messages",
                                     "can_send_polls", "can_send_other_messages", "can_add_web_page_previews",
                                     "can_manage_topics", "can_send_audios", "can_send_documents", "can_send_photos",
                                     "can_send_videos", "can_send_video_notes", "can_send_voice_notes")})
        p.update(is_member=is_member, until_date=0)
    elif status == "kicked":
        p.update(until_date=0)
    return p


class FakeRequest(BaseRequest):
    def __init__(self, rate_limit: int = None):
        self.sent = []          # (endpoint, params) for every message-producing call
        self.member_status = "member"
        self.member_is_member = True   # for "restricted": still in the chat?
        self.member_error = False      # getChatMember fails (Telegram trouble)
        self.member_error_text = "Bad Request: temporary failure"   # Telegram trouble, not our setup
        self.statuses = {}             # (chat_id, user_id) -> status, overrides member_status
        self.bot_admin_in = None       # chats where the bot (id 1) is admin; None = everywhere
        self.member_chats = []         # chat_id of every getChatMember call
        self.invite_links = 0          # createChatInviteLink calls
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
        elif endpoint == "createChatInviteLink":
            self.invite_links += 1
            result = {"invite_link": f"https://t.me/+invite{self.invite_links}_{params['chat_id']}",
                      "creator": {"id": 1, "is_bot": True, "first_name": "Bot"}, "creates_join_request": False,
                      "is_primary": False, "is_revoked": False}
        elif endpoint == "getChat":
            chat_id = str(params["chat_id"])
            result = {"id": -1001000000000, "type": "channel", "title": f"Title of {chat_id}",
                      "accent_color_id": 0, "max_reaction_count": 0}
        elif endpoint == "getChatMember":
            chat_id, user_id = str(params["chat_id"]), int(params["user_id"])
            if user_id == 1:  # the bot itself: admin check
                if self.bot_admin_in is not None and chat_id not in self.bot_admin_in:
                    return 400, json.dumps({"ok": False, "error_code": 400,
                                            "description": "Bad Request: member list is inaccessible"}).encode()
                result = member_payload("administrator", True, {"id": 1, "is_bot": True, "first_name": "Bot"})
            else:
                self.member_checks += 1
                self.member_chats.append(chat_id)
                if self.member_error:
                    return 400, json.dumps({"ok": False, "error_code": 400, "description": self.member_error_text}).encode()
                status = self.statuses.get((chat_id, user_id), self.member_status)
                result = member_payload(status, self.member_is_member, USER)
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


# What the test user picked at first start, unless a test says otherwise (setup=None
# leaves them a brand-new user, who gets the setup questions first).
TEST_SETUP = ("KES", "Africa/Nairobi")


class Harness:
    def __init__(self, flow_timeout=600, rate_limit=None, setup=TEST_SETUP):
        from app.main import build_application

        self.request = FakeRequest(rate_limit=rate_limit)
        self.app = build_application(request=self.request, flow_timeout=flow_timeout)
        self._n = 0
        self.setup = setup

    async def __aenter__(self):
        if self.setup:
            from app.db import init_db
            from app.services import prefs

            init_db()
            p = prefs.get_prefs(UID)
            prefs.set_prefs(UID, currency=None if p["currency"] else self.setup[0],
                            timezone=None if p["timezone"] else self.setup[1])
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

    async def location(self, latitude: float, longitude: float):
        n = self._next()
        message = {"message_id": 1000 + n, "date": 0, "chat": CHAT, "from": USER,
                   "location": {"latitude": latitude, "longitude": longitude}}
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
