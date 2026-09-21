"""Temporary end-to-end diagnostic: mention command -> moderation execution.

Runs the real cog set without connecting to Discord and feeds synthetic
messages through the real listener pipeline.
"""
import asyncio
import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

import main  # noqa: E402

GUILD_ID = 1489351990705131571
BOT_ID = 999999999999999999


class FakePermissions:
    def __init__(self, **flags):
        self.administrator = flags.get("administrator", False)
        self.ban_members = flags.get("ban_members", False)
        self.kick_members = flags.get("kick_members", False)
        self.moderate_members = flags.get("moderate_members", False)
        self.manage_roles = flags.get("manage_roles", False)
        self.manage_nicknames = flags.get("manage_nicknames", False)
        self.manage_channels = flags.get("manage_channels", False)
        self.manage_messages = flags.get("manage_messages", False)
        self.manage_webhooks = flags.get("manage_webhooks", False)


class FakeRole:
    def __init__(self, position, role_id):
        self.position = position
        self.id = role_id
        self.name = f"role-{role_id}"
        self.managed = False
        self.mention = f"<@&{role_id}>"

    def __ge__(self, other):
        return self.position >= getattr(other, "position", 0)

    def __gt__(self, other):
        return self.position > getattr(other, "position", 0)

    def __eq__(self, other):
        return self.position == getattr(other, "position", -1)


class FakeMember:
    def __init__(self, member_id, position, flags=None, guild=None):
        self.id = member_id
        self.mention = f"<@{member_id}>"
        self.top_role = FakeRole(position, 1000 + position)
        self.guild_permissions = FakePermissions(**(flags or {}))
        self.roles = [self.top_role]
        self.guild = guild
        self.bot = False
        self.display_name = f"member-{member_id}"
        self.name = f"member-{member_id}"
        self.calls = []

    async def kick(self, reason=None):
        self.calls.append(("kick", reason))

    async def ban(self, reason=None, delete_message_days=0):
        self.calls.append(("ban", reason))

    async def timeout(self, until, reason=None):
        self.calls.append(("timeout", until))

    async def send(self, *args, **kwargs):
        self.calls.append(("dm", args))

    async def edit(self, **kwargs):
        self.calls.append(("edit", kwargs))


class FakeChannel:
    def __init__(self, channel_id, guild):
        self.id = channel_id
        self.guild = guild
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self.purged = []
        self.permission_calls = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def purge(self, limit=0, **_kwargs):
        self.purged.append(limit)

    def overwrites_for(self, _role):
        class Overwrite:
            send_messages = None

        return Overwrite()

    async def set_permissions(self, _role, overwrite=None, reason=None):
        self.permission_calls.append(("set_permissions", overwrite, reason))

    async def edit(self, **kwargs):
        self.permission_calls.append(("edit", kwargs))
class FakeGuild:
    def __init__(self, guild_id, bot_member, owner_id=424242424242424242):
        self.id = guild_id
        self.name = "Diag Guild"
        self.owner_id = owner_id
        self.owner = None
        self.me = bot_member
        self.bans_recorded = []
        self.default_role = FakeRole(0, 1)
        self.channels = {}
        self.members = {}

    def get_member(self, member_id):
        return self.members.get(member_id)

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    def get_role(self, _role_id):
        return None

    async def ban(self, target, reason=None, delete_message_days=0):
        self.bans_recorded.append((getattr(target, "id", target), reason))

    async def unban(self, _user, reason=None):
        self.bans_recorded.append(("unban", reason))


class FakeMessage:
    def __init__(self, content, guild, author, channel, mentions=None):
        self.content = content
        self.guild = guild
        self.author = author
        self.channel = channel
        self.mentions = mentions or []
        self.channel_mentions = []
        self.role_mentions = []
        self.id = 555555555555555555
        self.webhook_id = None
        self.created_at = None
        self.reference = None
        self.attachments = []
        self.type = None
        self.edited_at = None
        self.flags = None
        self.guild = guild

    def mentioned_in(self, _user):
        return False


class FakeBotUser:
    def __init__(self, bot_id):
        self.id = bot_id
        self.bot = True
        self.display_name = "Shorekeeper"

    def mentioned_in(self, message):
        content = message.content or ""
        return f"<@{self.id}>" in content or f"<@!{self.id}>" in content


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_args):
        return self

    async def to_list(self, limit):
        return self._docs[:limit]


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        self.seq = 0

    async def create_index(self, *_args, **_kwargs):
        return None

    async def insert_one(self, doc):
        self.docs.append(doc)
        return object()

    async def count_documents(self, query):
        return len([doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())])

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self.seq += int(update.get("$inc", {}).get("seq", 1))
        return {"_id": query["_id"], "seq": self.seq}

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query):
        return FakeCursor([doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())])

    async def update_one(self, *_args, **_kwargs):
        return None


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection(key))
        return super().__getitem__(key)


class FakeCases:
    def __init__(self):
        self.docs = FakeCollection("moderation_cases")

    async def ensure_indexes(self):
        return None

    async def create_case(self, **kwargs):
        self.docs.seq += 1
        return {"case_id": self.docs.seq, **kwargs}

    async def find_case(self, _guild_id, _case_id):
        return None

    async def find_cases(self, *_args, **_kwargs):
        return []


def build_world(bot):
    flags = {
        "kick_members": True,
        "ban_members": True,
        "moderate_members": True,
        "manage_messages": True,
        "manage_channels": True,
        "manage_roles": True,
        "manage_nicknames": True,
    }
    bot_member = FakeMember(BOT_ID, 100, flags)
    guild = FakeGuild(GUILD_ID, bot_member)
    bot_member.guild = guild
    channel = FakeChannel(777777777777777777, guild)
    guild.channels[channel.id] = channel
    return guild, channel


async def run_case(bot, name, content, *, author_flags, target_id, target_position, target_bot=False):
    guild, channel = build_world(bot)
    db = FakeDb()
    core = bot.get_cog("ModerationCore")
    core.warns = db["warns"]
    core.mod_actions = db["mod_actions"]
    core.cases = FakeCases()

    author = FakeMember(313131313131313131, 50, author_flags, guild=guild)
    target = FakeMember(target_id, target_position, {}, guild=guild)
    target.bot = target_bot
    guild.members[author.id] = author
    guild.members[target.id] = target

    message = FakeMessage(content, guild, author, channel, mentions=[target])

    for listener in bot.extra_events.get("on_message", []):
        try:
            await listener(message)
        except Exception as exc:  # noqa: BLE001
            print(f"    [listener error] {getattr(listener, '__qualname__', listener)}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    printed = " | ".join(
        str(content_ if content_ is not None else kwargs.get("embed", ""))[:150]
        for content_, kwargs in channel.sent
    )
    print(f"--- {name}: {content}")
    print(f"    target.calls={target.calls}")
    print(f"    guild.bans={guild.bans_recorded}")
    print(f"    channel.purged={channel.purged}")
    print(f"    channel.perms={channel.permission_calls}")
    print(f"    channel.response={printed or '(nothing)'}")
    print(f"    warn_docs={len(db['warns'].docs)} action_docs={len(db['mod_actions'].docs)}")
    return target, channel


async def go():
    bot = main.MyBot()
    bot._connection.user = FakeBotUser(BOT_ID)
    for extension in bot.discover_extensions():
        try:
            await bot.load_extension(extension)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAILED] {extension}: {type(exc).__name__}: {exc}")

    print("ModerationCore loaded:", bot.get_cog("ModerationCore") is not None)
    print("extra_events[on_message]:", getattr(bot, "extra_events", {}).get("on_message"))
    print("_listeners keys:", sorted(getattr(bot, "_listeners", {}).keys()))
    for key, value in getattr(bot, "_listeners", {}).items():
        print("   ", key, value)

    admin = {
        "administrator": True,
        "kick_members": True,
        "ban_members": True,
        "moderate_members": True,
        "manage_messages": True,
        "manage_channels": True,
    }
    cases = [
        ("KICK ok", f"<@{BOT_ID}> kick <@111111111111111111>", 111111111111111111, 5),
        ("BAN ok", f"<@{BOT_ID}> ban <@222222222222222222> ; spamming", 222222222222222222, 5),
        ("WARN ok", f"<@{BOT_ID}> warn <@333333333333333333> ; rude", 333333333333333333, 5),
        ("TIMEOUT ok", f"<@{BOT_ID}> timeout <@444444444444444444> 10m ; cooldown", 444444444444444444, 5),
        ("UNMUTE ok", f"<@{BOT_ID}> unmute <@444444444444444444> ; apology", 444444444444444444, 5),
        ("PURGE ok", f"<@{BOT_ID}> purge 20", 555555555555555555, 5),
        ("LOCK ok", f"<@{BOT_ID}> lock", 666666666666666666, 5),
        ("UNLOCK ok", f"<@{BOT_ID}> unlock", 666666666666666666, 5),
        ("SLOWMODE ok", f"<@{BOT_ID}> slowmode 30s", 666666666666666666, 5),
        ("HIERARCHY above bot", f"<@{BOT_ID}> kick <@777777777777777777>", 777777777777777777, 500),
        ("HIERARCHY equal bot", f"<@{BOT_ID}> kick <@888888888888888888>", 888888888888888888, 100),
        ("OWNER SHIELD", f"<@{BOT_ID}> ban <@424242424242424242>", 424242424242424242, 1),
        ("ACTOR HIERARCHY peer", f"<@{BOT_ID}> kick <@919191919191919191>", 919191919191919191, 50),
    ]
    for name, content, target_id, position in cases:
        await run_case(
            bot,
            name,
            content,
            author_flags=admin,
            target_id=target_id,
            target_position=position,
        )

    # Unactivated guild must never execute a moderation action.
    from cogs.core import constants

    print("owner id constant:", constants.SOLE_OWNER_ID)


asyncio.run(go())