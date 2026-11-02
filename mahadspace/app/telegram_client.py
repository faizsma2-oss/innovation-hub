"""Talking to Telegram as the connected user (Telethon), or to a fake Telegram for tests and demos.

Settings (environment variables):
  TELEGRAM_API_ID, TELEGRAM_API_HASH   from https://my.telegram.org → API development tools
  MAHADSPACE_DISCUSSION_GROUP         the Discussion group: @username, t.me link or numeric ID
  MAHADSPACE_VIP_GROUP                the VIP group, the same way
  MAHADSPACE_TELEGRAM=fake            use the built-in fake Telegram (no real account needed)

The login is stored as a Telethon "string session" in the database, so each request reconnects without
keeping a client open. Nothing here decides who gets a message: the routes do, and only after a person
has selected recipients and typed SEND.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

GROUPS = ("discussion", "vip")
SEND_DELAY_SECONDS = float(os.environ.get("MAHADSPACE_SEND_DELAY", "1.5"))


class TelegramError(Exception):
    """A problem to show the person, in plain words."""


def group_ref(group: str) -> str | None:
    return os.environ.get(f"MAHADSPACE_{group.upper()}_GROUP") or None


def get_gateway():
    if os.environ.get("MAHADSPACE_TELEGRAM") == "fake":
        return FAKE
    return TelethonGateway()


def display_name(user) -> str:
    return " ".join(part for part in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if part).strip()


# ── Real Telegram ────────────────────────────────────────────────────────────

class TelethonGateway:
    def __init__(self):
        self.api_id = os.environ.get("TELEGRAM_API_ID")
        self.api_hash = os.environ.get("TELEGRAM_API_HASH")

    async def _client(self, session: str | None):
        if not self.api_id or not self.api_hash:
            raise TelegramError("Telegram API credentials are not configured on the server (TELEGRAM_API_ID and "
                                "TELEGRAM_API_HASH).")
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(session or None), int(self.api_id), self.api_hash)
        await client.connect()
        return client

    async def _authorized(self, session: str):
        client = await self._client(session)
        if not await client.is_user_authorized():
            await client.disconnect()
            raise TelegramError("Reconnect Telegram: the saved session has expired.")
        return client

    async def send_code(self, phone: str) -> tuple[str, str]:
        from telethon import errors
        client = await self._client(None)
        try:
            sent = await client.send_code_request(phone)
            return client.session.save(), sent.phone_code_hash
        except errors.PhoneNumberInvalidError:
            raise TelegramError("That phone number isn't valid for Telegram. Include the country code.")
        except errors.FloodWaitError as error:
            raise TelegramError(f"Telegram asks you to wait {error.seconds} seconds before requesting another code.")
        finally:
            await client.disconnect()

    async def sign_in_code(self, session: str, phone: str, code: str, phone_code_hash: str) -> tuple[str, bool]:
        from telethon import errors
        client = await self._client(session)
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            return client.session.save(), False
        except errors.SessionPasswordNeededError:
            return client.session.save(), True
        except errors.PhoneCodeInvalidError:
            raise TelegramError("That code is not correct. Enter the newest code Telegram sent.")
        except errors.PhoneCodeExpiredError:
            raise TelegramError("That code has expired. Request a new code.")
        finally:
            await client.disconnect()

    async def sign_in_password(self, session: str, password: str) -> str:
        from telethon import errors
        client = await self._client(session)
        try:
            await client.sign_in(password=password)
            return client.session.save()
        except errors.PasswordHashInvalidError:
            raise TelegramError("The two-step verification password is incorrect.")
        finally:
            await client.disconnect()

    async def whoami(self, session: str) -> dict | None:
        client = await self._client(session)
        try:
            if not await client.is_user_authorized():
                return None
            me = await client.get_me()
            return {"id": str(me.id), "name": display_name(me) or me.username or str(me.id)}
        finally:
            await client.disconnect()

    async def group_members(self, session: str, ref: str) -> tuple[str, list[dict]]:
        client = await self._authorized(session)
        try:
            entity = await client.get_entity(int(ref) if ref.lstrip("-").isdigit() else ref)
            me = await client.get_me()
            users = await client.get_participants(entity)
            return (getattr(entity, "title", ref),
                    [{"telegram_id": str(u.id), "display_name": display_name(u), "username": u.username or "",
                      "access_hash": str(u.access_hash or "")}
                     for u in users if not u.bot and not u.deleted and u.id != me.id])
        except TelegramError:
            raise
        except Exception as error:  # noqa: BLE001 - any Telegram failure becomes a message for the page
            raise TelegramError(f"Could not read the group {ref}: {error}")
        finally:
            await client.disconnect()

    async def send_messages(self, session: str, recipients: list[dict], text: str) -> list[dict]:
        from telethon import errors, types
        client = await self._authorized(session)
        results, stop = [], None
        try:
            for index, recipient in enumerate(recipients):
                if stop:
                    results.append(recipient | {"error": stop})
                    continue
                try:
                    peer = types.InputPeerUser(int(recipient["telegram_id"]), int(recipient.get("access_hash") or 0))
                    await client.send_message(peer, text)
                    results.append(recipient | {"error": None})
                except errors.FloodWaitError as error:
                    stop = f"Telegram asked to pause for {error.seconds} seconds; not sent"
                    results.append(recipient | {"error": stop})
                except (errors.UserIsBlockedError, errors.InputUserDeactivatedError, errors.PeerIdInvalidError,
                        errors.UserPrivacyRestrictedError, ValueError) as error:
                    results.append(recipient | {"error": type(error).__name__.replace("Error", "")})
                if index < len(recipients) - 1 and not stop:
                    await asyncio.sleep(SEND_DELAY_SECONDS)   # stay well inside Telegram's limits
            return results
        finally:
            await client.disconnect()

    async def incoming(self, session: str, days: int, peers: list[dict] | None) -> tuple[list[dict], int]:
        """Incoming private messages from the last `days` days: from `peers`, or from every private chat."""
        from telethon import types
        client = await self._authorized(session)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        messages, chats = [], 0
        try:
            if peers is None:
                targets = [(d.entity, d.name) async for d in client.iter_dialogs(limit=500)
                           if d.is_user and not getattr(d.entity, "bot", False)]
            else:
                targets = [(types.InputPeerUser(int(p["telegram_id"]), int(p.get("access_hash") or 0)),
                            p.get("display_name") or "") for p in peers]
            for peer, name in targets:
                chats += 1
                try:
                    async for message in client.iter_messages(peer, limit=100):
                        if message.date < cutoff:
                            break
                        if message.out or not message.message:
                            continue
                        sender = await message.get_sender()
                        messages.append({"telegram_id": str(message.sender_id), "message_id": str(message.id),
                                         "display_name": display_name(sender) or name,
                                         "username": getattr(sender, "username", "") or "",
                                         "access_hash": str(getattr(sender, "access_hash", "") or ""),
                                         "chat_name": name, "text": message.message,
                                         "date": message.date.isoformat(timespec="seconds")})
                except ValueError:
                    continue                 # a chat Telegram won't open with the stored details
            return messages, chats
        finally:
            await client.disconnect()

    async def remove_from_group(self, session: str, ref: str, member: dict):
        from telethon import types
        client = await self._authorized(session)
        try:
            entity = await client.get_entity(int(ref) if ref.lstrip("-").isdigit() else ref)
            await client.kick_participant(entity, types.InputPeerUser(int(member["telegram_id"]),
                                                                      int(member.get("access_hash") or 0)))
        except TelegramError:
            raise
        except Exception as error:  # noqa: BLE001
            raise TelegramError(str(error) or type(error).__name__)
        finally:
            await client.disconnect()

    async def log_out(self, session: str):
        try:
            client = await self._client(session)
        except TelegramError:
            return
        try:
            if await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()


# ── Fake Telegram (tests and demos) ──────────────────────────────────────────

class FakeGateway:
    """Behaves like Telegram for one demo account. Code 12345; phones ending in 2 also need password "hunter2"."""
    CODE, PASSWORD = "12345", "hunter2"

    def __init__(self):
        self.reset()

    def reset(self):
        self.groups = {
            "discussion": ("MahadSpace Discussion (demo)", [
                {"telegram_id": "1001", "display_name": "Ali Hassan", "username": "alihassan", "access_hash": "1"},
                {"telegram_id": "1002", "display_name": "Sara Khan", "username": "sarak", "access_hash": "2"},
                {"telegram_id": "1003", "display_name": "Omar Farooq", "username": "", "access_hash": "3"},
                {"telegram_id": "1004", "display_name": "Ayesha Malik", "username": "ayesha_m", "access_hash": "4"},
            ]),
            "vip": ("MahadSpace VIP (demo)", [
                {"telegram_id": "1001", "display_name": "Ali Hassan", "username": "alihassan", "access_hash": "1"},
                {"telegram_id": "1005", "display_name": "Bilal Ahmed", "username": "bilal", "access_hash": "5"},
            ]),
        }
        self.inbox: list[dict] = []        # messages members sent to the connected account
        self.sent: list[dict] = []
        self.removed: list[tuple[str, str]] = []

    @staticmethod
    def _check(session: str | None):
        if not session or not session.startswith("fake-authorized"):
            raise TelegramError("Reconnect Telegram: the saved session has expired.")

    async def send_code(self, phone: str):
        return f"fake-pending:{phone}", "fake-hash"

    async def sign_in_code(self, session, phone, code, phone_code_hash):
        if code != self.CODE:
            raise TelegramError("That code is not correct. Enter the newest code Telegram sent.")
        if phone.endswith("2"):
            return f"fake-password:{phone}", True
        return f"fake-authorized:{phone}", False

    async def sign_in_password(self, session, password):
        if password != self.PASSWORD:
            raise TelegramError("The two-step verification password is incorrect.")
        return "fake-authorized:" + session.split(":", 1)[1]

    async def whoami(self, session):
        return {"id": "999", "name": "Demo Account"} if session and session.startswith("fake-authorized") else None

    async def group_members(self, session, ref):
        self._check(session)
        group = {"demo-discussion": "discussion", "demo-vip": "vip"}.get(ref, ref)
        if group not in self.groups:
            raise TelegramError(f"Could not read the group {ref}: not found")
        title, members = self.groups[group]
        return title, [dict(m) for m in members]

    async def send_messages(self, session, recipients, text):
        self._check(session)
        results = []
        for recipient in recipients:
            if recipient["telegram_id"] == "1004":
                results.append(recipient | {"error": "UserPrivacyRestricted"})
                continue
            self.sent.append({"telegram_id": recipient["telegram_id"], "text": text})
            results.append(recipient | {"error": None})
        return results

    async def incoming(self, session, days, peers):
        self._check(session)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        wanted = None if peers is None else {p["telegram_id"] for p in peers}
        messages = [m for m in self.inbox if m["date"] >= cutoff and (wanted is None or m["telegram_id"] in wanted)]
        chats = len({m["telegram_id"] for m in self.inbox}) if peers is None else len(peers)
        return [dict(m) for m in messages], chats

    async def remove_from_group(self, session, ref, member):
        self._check(session)
        group = {"demo-discussion": "discussion", "demo-vip": "vip"}.get(ref, ref)
        title, members = self.groups[group]
        self.groups[group] = (title, [m for m in members if m["telegram_id"] != member["telegram_id"]])
        self.removed.append((group, member["telegram_id"]))

    async def log_out(self, session):
        return None


FAKE = FakeGateway()
