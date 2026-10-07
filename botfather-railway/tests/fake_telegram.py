"""شبیه‌ساز سبک تلگرام برای تست هندلرها بدون اتصال واقعی."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pyrogram import ContinuePropagation, StopPropagation
from pyrogram.enums import ChatType
from pyrogram.errors import UserNotParticipant
from pyrogram.types import CallbackQuery as _CQ
from pyrogram.types import Message as _Msg


class FakeUser(SimpleNamespace):
    def __init__(self, id: int, first_name="کاربر", username=None):
        super().__init__(id=id, first_name=first_name, username=username,
                         is_bot=False, is_self=False)


class FakeChat(SimpleNamespace):
    def __init__(self, id: int, type=ChatType.PRIVATE):
        super().__init__(id=id, type=type, username=None, title=None)


class _Str(str):
    """رشته‌ای که مثل pyrogram.types.Str خاصیت .html دارد."""

    @property
    def html(self):
        return str(self)

    @property
    def markdown(self):
        return str(self)


class FakeMessage(_Msg):
    """از Message ارث می‌برد تا isinstance در فیلترهای pyrogram درست کار کند."""

    _next_id = 100

    def __init__(self, client, user: FakeUser, text=None, chat=None,
                 reply_to=None, media_kind=None, caption=None, msg_id=None):
        FakeMessage._next_id += 1
        self.id = msg_id if msg_id is not None else FakeMessage._next_id
        self.client = client
        self.from_user = user
        self.chat = chat or FakeChat(user.id)
        self.text = _Str(text) if text is not None else None
        self.caption = _Str(caption) if caption is not None else None
        self.reply_to_message = reply_to
        # pyrogram در filters.reply این فیلد را می‌خواند، نه reply_to_message را
        self.reply_to_message_id = reply_to.id if reply_to else None
        self.reply_to_top_message_id = None
        self.reply_to_story_id = None
        # بعضی فیلدها در نسخه‌های جدید (kurigram) property فقط‌خواندنی‌اند
        for attr, val in (
            ("outgoing", False), ("date", None), ("command", None),
            ("edit_date", None), ("mentioned", None), ("service", None),
            ("media", media_kind), ("empty", False), ("forward_date", None),
            ("via_bot", None), ("forward_from", None), ("forward_origin", None),
            ("photo", None), ("video", None), ("document", None), ("audio", None),
            ("voice", None), ("animation", None), ("sticker", None),
            ("scheduled", False), ("from_scheduled", False), ("media_group_id", None),
        ):
            try:
                setattr(self, attr, val)
            except AttributeError:
                pass
        if media_kind:
            object.__setattr__(self, media_kind, SimpleNamespace(
                file_id=f"MOTHER_FILEID_{self.id}",
                file_unique_id=f"UNIQ{self.id}",
                file_name=f"test_{media_kind}.bin",
            ))

    # ---- متدهایی که کد ما صدا می‌زند ----
    async def reply(self, text, **kwargs):
        return await self.client.send_message(self.chat.id, text, **kwargs)

    reply_text = reply

    async def copy(self, chat_id, **kwargs):
        self.client.log.append(
            {"action": "copy", "chat_id": chat_id, "text": str(self.text or self.caption or ""),
             "media": self.media}
        )
        return FakeMessage(self.client, self.from_user, text=str(self.text or ""))

    async def edit_text(self, text, **kwargs):
        self.text = _Str(text)
        self.client.log.append({"action": "edit", "chat_id": self.chat.id, "text": text,
                                "reply_markup": kwargs.get("reply_markup")})
        return self

    async def edit_reply_markup(self, markup):
        self.client.log.append({"action": "edit_markup", "reply_markup": markup})
        return self

    async def delete(self):
        self.client.log.append({"action": "delete", "id": self.id})


class FakeCallbackQuery(_CQ):
    """از CallbackQuery ارث می‌برد تا filters.regex آن را بشناسد."""

    def __init__(self, client, user: FakeUser, data: str, message: FakeMessage):
        self.client = client
        self.from_user = user
        self.data = data
        self.message = message
        self.id = "cbq"
        self.matches = None
        self.inline_message_id = None
        self.chat_instance = "ci"
        self.game_short_name = None

    async def answer(self, text="", show_alert=False):
        # fix: مثل تلگرام واقعی، جواب‌دادنِ دوم به همان کال‌بک خطا می‌دهد
        if getattr(self, "_answered", False):
            from pyrogram.errors import QueryIdInvalid
            raise QueryIdInvalid()
        self._answered = True
        self.client.log.append({"action": "answer", "text": text, "alert": show_alert})


class FakeClient:
    """کلاینت تقلبی: پیام‌ها را در log ثبت می‌کند و عضویت را شبیه‌سازی می‌کند."""

    def __init__(self, bot_id=1, username="test_bot", memberships=None,
                 admin_of=None, raise_for=None, chats=None, posts=None,
                 reactions=None, history_ok=True, reactions_list_error=None):
        self.log: list[dict] = []
        self.me = SimpleNamespace(id=bot_id, username=username, is_bot=True,
                                  first_name=username)
        # memberships: {channel: set(user_ids)}
        self.memberships = memberships or {}
        self.admin_of = admin_of or set()
        self.raise_for = raise_for or {}   # {channel: Exception}
        self.uploads: list[str] = []
        # ── سمت «تلگرام» برای وظیفه‌ی ری‌اکشن ──
        # chats: {"@ch": -1001}  posts: {-1001: [msg_id, ...]}
        # reactions: {(-1001, msg_id): {user_id, ...}}
        self.chats = chats or {}
        self.posts = posts or {}
        self.reactions = reactions or {}
        self.history_ok = history_ok
        self.reactions_list_error = reactions_list_error
        self.invokes: list = []

    # ---------- شبیه‌سازی MTProto برای وظیفه‌ی ری‌اکشن ----------
    def _chat_id_of(self, ref):
        if isinstance(ref, str):
            if ref in self.chats:
                return self.chats[ref]
            raise ValueError(f"چت ناشناخته: {ref}")
        return int(ref)

    async def get_chat(self, ref):
        chat_id = self._chat_id_of(ref)
        uname = None
        for k, v in self.chats.items():
            if v == chat_id and isinstance(k, str):
                uname = k.lstrip("@")
        return SimpleNamespace(id=chat_id, username=uname, type="channel")

    async def resolve_peer(self, ref):
        chat_id = self._chat_id_of(ref)
        return SimpleNamespace(channel_id=abs(chat_id) - 1000000000000
                               if str(chat_id).startswith("-100") else chat_id,
                               _chat_id=chat_id)

    async def get_chat_history(self, chat_id, limit=100):
        if not self.history_ok:
            raise RuntimeError("BOT_METHOD_INVALID")
        for mid in sorted(self.posts.get(int(chat_id), []), reverse=True)[:limit]:
            yield FakeMessage(self, FakeUser(self.me.id), text=f"post {mid}",
                              msg_id=mid)

    async def get_messages(self, chat_id, message_ids):
        """channels.getMessages — برای ربات‌ها مجاز است (مسیر backfill).

        پست‌های موجود به‌صورت Message واقعی و آیدی‌های ناموجود به‌صورت
        empty=True برمی‌گردند (مثل تلگرام واقعی).
        """
        ids = message_ids if isinstance(message_ids, (list, tuple)) else [message_ids]
        out = []
        for mid in ids:
            mid = int(mid)
            if mid in self.posts.get(int(chat_id), []):
                out.append(FakeMessage(self, FakeUser(self.me.id),
                                       text=f"post {mid}", msg_id=mid))
            else:
                out.append(SimpleNamespace(id=mid, empty=True))
        return out

    async def invoke(self, query):
        self.invokes.append(query)
        name = type(query).__name__
        if name == "GetMessageReactionsList":
            if self.reactions_list_error:
                raise self.reactions_list_error
            chat_id = getattr(query.peer, "_chat_id", None)
            users = self.reactions.get((chat_id, int(query.id)), set())
            return SimpleNamespace(reactions=[
                SimpleNamespace(peer_id=SimpleNamespace(user_id=u))
                for u in sorted(users)])
        raise NotImplementedError(name)

    # کمکی تست: کاربر روی پست ری‌اکشن می‌زند / برمی‌دارد
    def react(self, chat_id, msg_id, user_id, on=True):
        key = (int(chat_id), int(msg_id))
        self.posts.setdefault(int(chat_id), [])
        if msg_id not in self.posts[int(chat_id)]:
            self.posts[int(chat_id)].append(int(msg_id))
        s = self.reactions.setdefault(key, set())
        s.add(user_id) if on else s.discard(user_id)

    async def get_me(self):
        return self.me

    async def send_message(self, chat_id, text, **kwargs):
        self.log.append({"action": "send_message", "chat_id": chat_id, "text": str(text),
                         "reply_markup": kwargs.get("reply_markup")})
        return FakeMessage(self, FakeUser(self.me.id, self.me.username), text=str(text))

    async def _send_media(self, kind, chat_id, source, **kwargs):
        self.uploads.append(str(source))
        self.log.append({"action": f"send_{kind}", "chat_id": chat_id,
                         "source": str(source), "caption": kwargs.get("caption")})
        msg = FakeMessage(self, FakeUser(self.me.id), media_kind=kind)
        return msg

    async def send_photo(self, chat_id, source, **kw):
        return await self._send_media("photo", chat_id, source, **kw)

    async def send_video(self, chat_id, source, **kw):
        return await self._send_media("video", chat_id, source, **kw)

    async def send_document(self, chat_id, source, **kw):
        return await self._send_media("document", chat_id, source, **kw)

    async def send_audio(self, chat_id, source, **kw):
        return await self._send_media("audio", chat_id, source, **kw)

    async def send_voice(self, chat_id, source, **kw):
        return await self._send_media("voice", chat_id, source, **kw)

    async def send_animation(self, chat_id, source, **kw):
        return await self._send_media("animation", chat_id, source, **kw)

    async def send_sticker(self, chat_id, source, **kw):
        return await self._send_media("sticker", chat_id, source, **kw)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.log.append({"action": "edit", "chat_id": chat_id, "id": message_id,
                         "text": str(text), "reply_markup": kwargs.get("reply_markup")})
        return FakeMessage(self, FakeUser(self.me.id), text=str(text))

    async def get_chat_member(self, channel, user_id):
        if channel in self.raise_for:
            raise self.raise_for[channel]
        members = self.memberships.get(channel)
        if members is None:
            raise UserNotParticipant()
        if user_id in members:
            from pyrogram.enums import ChatMemberStatus
            status = (ChatMemberStatus.ADMINISTRATOR
                      if user_id == self.me.id and channel in self.admin_of
                      else ChatMemberStatus.MEMBER)
            return SimpleNamespace(status=status, user=FakeUser(user_id))
        raise UserNotParticipant()

    async def download_media(self, message, file_name=None):
        import pathlib
        p = pathlib.Path(file_name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" * 512)
        return str(p)

    # ---- کمکی‌های تست ----
    def sent_texts(self, chat_id=None):
        return [e["text"] for e in self.log
                if e["action"] == "send_message" and (chat_id is None or e["chat_id"] == chat_id)]

    def last(self, action=None):
        for e in reversed(self.log):
            if action is None or e["action"] == action:
                return e
        return None

    def clear(self):
        self.log.clear()
        self.uploads.clear()


async def dispatch(app, client, update, kind="message"):
    """آپدیت را دقیقاً مثل dispatcher پایروگرام از فیلترها عبور می‌دهد."""
    from pyrogram.handlers import CallbackQueryHandler, MessageHandler

    want = MessageHandler if kind == "message" else CallbackQueryHandler
    fired = []
    for group in sorted(app.dispatcher.groups):
        for handler in app.dispatcher.groups[group]:
            if not isinstance(handler, want):
                continue
            try:
                ok = await handler.check(client, update)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                fired.append(handler.callback.__name__)
                try:
                    await handler.callback(client, update)
                except StopPropagation:
                    return fired          # دقیقاً مثل دیسپچر واقعی
                except ContinuePropagation:
                    continue
                break  # در هر گروه فقط اولین هندلر منطبق اجرا می‌شود
    return fired
