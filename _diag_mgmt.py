"""Temporary diagnostic: management commands + authorization pipeline."""
import asyncio
import copy
import json
import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

import cogs.server_config as sc  # noqa: E402

CONFIG_PATH = BASE_DIR / sc.CONFIG_PATH
MEM = {"config": json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}


def fake_load():
    return copy.deepcopy(MEM["config"])


def fake_save(config):
    MEM["config"] = copy.deepcopy(config)


# Keep the on-disk production config untouched.
sc.load_config = fake_load
sc.save_config = fake_save

import main  # noqa: E402

GUILD_ID = 1489351990705131571
BOT_ID = 999999999999999999
OWNER_ID = 708390973712891976

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}")


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
    def __init__(self, position, role_id, name="role"):
        self.position = position
        self.id = role_id
        self.name = name
        self.managed = False
        self.mention = f"<@&{role_id}>"

    def __ge__(self, other):
        return self.position >= getattr(other, "position", 0)

    def __gt__(self, other):
        return self.position > getattr(other, "position", 0)

    def __eq__(self, other):
        return self.position == getattr(other, "position", -1)

    def __hash__(self):
        return hash((self.position, self.id))


class FakeMember:
    def __init__(self, member_id, position, flags=None, guild=None):
        self.id = member_id
        self.mention = f"<@{member_id}>"
        self.top_role = FakeRole(position, 900000 + position)
        self.guild_permissions = FakePermissions(**(flags or {}))
        self.roles = [self.top_role]
        self.guild = guild
        self.bot = False
        self.display_name = f"member-{member_id}"
        self.name = f"member-{member_id}"
        self.calls = []

    async def kick(self, reason=None):
        self.calls.append(("kick", reason))

    async def timeout(self, until, reason=None):
        self.calls.append(("timeout", until))

    async def edit(self, **kwargs):
        self.calls.append(("edit", kwargs))

    async def add_roles(self, *roles, reason=None):
        self.calls.append(("add_roles", [getattr(role, "name", role) for role in roles]))

    async def remove_roles(self, *roles, reason=None):
        self.calls.append(("remove_roles", [getattr(role, "name", role) for role in roles]))

    async def send(self, *args, **kwargs):
        self.calls.append(("dm", args))


class FakeOverwrite:
    send_messages = None
    add_reactions = None
    create_public_threads = None
    view_channel = None


class FakeChannelPermissions:
    manage_channels = True
    send_messages = True


class FakeChannel:
    def __init__(self, channel_id, guild, name="general"):
        self.id = channel_id
        self.guild = guild
        self.name = name
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self.calls = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content if content is not None else kwargs.get("embed"))

    def overwrites_for(self, _role):
        return FakeOverwrite()

    def permissions_for(self, _member):
        return FakeChannelPermissions()

    async def webhooks(self):
        return []

    async def set_permissions(self, *_args, **_kwargs):
        self.calls.append("set_permissions")

    async def edit(self, **kwargs):
        self.calls.append(("edit", kwargs))


class FakeGuild:
    def __init__(self, guild_id, bot_member, owner_id=424242424242424242):
        self.id = guild_id
        self.name = "Diag Guild"
        self.owner_id = owner_id
        self.owner = None
        self.me = bot_member
        self.members = {}
        self.channels = {}
        self.roles = []
        self.default_role = FakeRole(0, 1, "everyone")

    @property
    def text_channels(self):
        return list(self.channels.values())

    def get_member(self, member_id):
        return self.members.get(member_id)

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    def get_role(self, role_id):
        for role in self.roles:
            if role.id == role_id:
                return role
        return None
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
        self.flags = None
        self.pinned = False
        self.tts = False
        self.embeds = []
        self.reactions = []

    def mentioned_in(self, _user):
        return False


class FakeBotUser:
    id = BOT_ID
    bot = True
    display_name = "Shorekeeper"

    def mentioned_in(self, message):
        content = message.content or ""
        return f"<@{self.id}>" in content or f"<@!{self.id}>" in content


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def to_list(self, limit=50):
        return self._docs[:limit]


class FakeResult:
    deleted_count = 1


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

    async def update_one(self, *_args, **_kwargs):
        return None

    async def delete_one(self, *_args, **_kwargs):
        return FakeResult()

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


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection(key))
        return super().__getitem__(key)


class FakeCases:
    def __init__(self):
        self.created = []

    async def ensure_indexes(self):
        return None

    async def create_case(self, **kwargs):
        case_id = 1000 + len(self.created) + 1
        self.created.append(case_id)
        return {"case_id": case_id, **kwargs}

    async def find_case(self, _guild_id, case_id):
        if int(case_id) == 1042:
            return {
                "case_id": 1042,
                "action": "BAN",
                "target_id": 111111111111111111,
                "moderator_id": 313131313131313131,
                "reason": "raid attempt",
            }
        return None

    async def find_cases(self, _guild_id, _target_id, limit=10):
        return [
            {"case_id": 1041, "action": "WARN", "reason": "spam"},
            {"case_id": 1042, "action": "BAN", "reason": "raid attempt"},
        ]


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
    role = FakeRole(5, 555000, "verified")
    guild.roles.append(role)
    channel = FakeChannel(777777777777777777, guild)
    guild.channels[channel.id] = channel
    return guild, channel, role


def patch_stores(bot):
    db = FakeDb()
    for name in ("ModerationCore", "NickLockCog", "MiscToolsCog"):
        cog = bot.get_cog(name)
        if not cog:
            continue
        for attr in ("warns", "mod_actions", "nick_locks", "bark_locks", "uwu_locks", "afk", "webhook_cache"):
            if hasattr(cog, attr):
                setattr(cog, attr, db[attr] if attr != "webhook_cache" else {})
    core = bot.get_cog("ModerationCore")
    core.cases = FakeCases()
async def dispatch(bot, message):
    for listener in bot.extra_events.get("on_message", []):
        try:
            await listener(message)
        except Exception as exc:  # noqa: BLE001
            print(f"    [listener error] {getattr(listener, '__qualname__', listener)}: {type(exc).__name__}: {exc}")
            traceback.print_exc()


async def run_command(bot, name, content, *, actor_id=OWNER_ID, actor_flags=None, target_id=None, mentions=None):
    guild, channel, role = build_world(bot)
    default_flags = {
        "administrator": True,
        "kick_members": True,
        "ban_members": True,
        "moderate_members": True,
        "manage_messages": True,
        "manage_channels": True,
        "manage_roles": True,
        "manage_nicknames": True,
    }
    actor = FakeMember(actor_id, 90, actor_flags or default_flags, guild=guild)
    guild.members[actor.id] = actor
    target = None
    if target_id:
        target = FakeMember(target_id, 5, {}, guild=guild)
        guild.members[target.id] = target
    mentioned = mentions if mentions is not None else ([target] if target else [])
    message = FakeMessage(content, guild, actor, channel, mentions=mentioned)
    await dispatch(bot, message)
    rendered = " | ".join(
        (
            str(entry)
            if not hasattr(entry, "description")
            else f"embed:{getattr(entry, 'title', '')}:{getattr(entry, 'description', '')}"
        )
        for entry in channel.sent
    )
    print(f"--- {name}: {content}")
    print(f"    response={rendered or '(nothing)'}")
    if target:
        print(f"    target.calls={target.calls}")
    return guild, channel, target, rendered


def guild_cfg():
    return MEM["config"]["guilds"][str(GUILD_ID)]


async def boot():
    bot = main.MyBot()
    bot._connection.user = FakeBotUser()
    failures = []
    for extension in bot.discover_extensions():
        try:
            await bot.load_extension(extension)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{extension}: {type(exc).__name__}: {exc}")
    check("all extensions load", not failures, str(failures))
    patch_stores(bot)
    guild_cfg()["enabled"] = True
    guild_cfg()["modules"] = {}
    return bot


async def scenarios(bot):
    # 1. Guild activation is owner-only.
    _g, _c, _t, rendered = await run_command(
        bot, "guild disable by administrator", f"<@{BOT_ID}> guild disable", actor_id=909090909090909091
    )
    check("administrator cannot disable guild", "Permission Denied" in rendered and guild_cfg()["enabled"] is True, rendered)

    _g, _c, _t, rendered = await run_command(bot, "guild status (owner)", f"<@{BOT_ID}> guild status")
    check("owner guild status reports active", "active" in rendered, rendered)

    _g, _c, _t, rendered = await run_command(bot, "guild disable (owner)", f"<@{BOT_ID}> guild disable")
    check("owner can disable guild", guild_cfg()["enabled"] is False, rendered)

    _g, _c, target, rendered = await run_command(
        bot, "kick while guild inactive", f"<@{BOT_ID}> kick <@111111111111111111>", target_id=111111111111111111
    )
    check("inactive guild blocks moderation", "not activated" in rendered and target.calls == [], rendered)

    _g, _c, _t, rendered = await run_command(bot, "guild enable (owner)", f"<@{BOT_ID}> guild enable")
    check("owner can re-enable guild", guild_cfg()["enabled"] is True, rendered)

    # 2. Module system gates execution.
    _g, _c, _t, rendered = await run_command(bot, "module disable moderation", f"<@{BOT_ID}> module disable moderation")
    check("module disable persists", guild_cfg()["modules"].get("moderation") == "disabled", str(guild_cfg()["modules"]))

    _g, _c, target, rendered = await run_command(
        bot, "kick while module disabled", f"<@{BOT_ID}> kick <@121212121212121212>", target_id=121212121212121212
    )
    check("disabled module blocks kick", target.calls == [] and not rendered.strip(), f"calls={target.calls} rendered={rendered!r}")

    _g, _c, _t, rendered = await run_command(bot, "module active moderation", f"<@{BOT_ID}> module active moderation")
    check("module active persists", guild_cfg()["modules"].get("moderation") == "active", str(guild_cfg()["modules"]))

    _g, _c, target, rendered = await run_command(
        bot, "kick after module re-enable", f"<@{BOT_ID}> kick <@131313131313131313>", target_id=131313131313131313
    )
    check("kick works again", any(call[0] == "kick" for call in target.calls), f"calls={target.calls}")

    # 3. Lockdown is reversible and gated.
    _g, _c, _t, rendered = await run_command(
        bot, "lockdown on by administrator", f"<@{BOT_ID}> lockdown on", actor_id=909090909090909091
    )
    check("administrator cannot lockdown", "Permission Denied" in rendered and not guild_cfg()["lockdown"]["enabled"], rendered)

    _g, _c, _t, rendered = await run_command(bot, "lockdown on (owner)", f"<@{BOT_ID}> lockdown on")
    check("owner lockdown on", guild_cfg()["lockdown"]["enabled"] is True, rendered)

    _g, _c, _t, rendered = await run_command(bot, "lockdown status", f"<@{BOT_ID}> lockdown status")
    check("lockdown status active", "active" in rendered, rendered)

    _g, _c, _t, rendered = await run_command(bot, "lockdown off (owner)", f"<@{BOT_ID}> lockdown off")
    check("owner lockdown off", guild_cfg()["lockdown"]["enabled"] is False, rendered)

    # 4. Case system.
    _g, _c, _t, rendered = await run_command(bot, "case lookup", f"<@{BOT_ID}> case 1042")
    check("case lookup 1042", "1042" in rendered and "BAN" in rendered, rendered)

    _g, _c, _t, rendered = await run_command(
        bot, "cases for user", f"<@{BOT_ID}> cases <@111111111111111111>", target_id=111111111111111111
    )
    check("cases list", "1041" in rendered and "1042" in rendered, rendered)

    # 5. Role operations.
    _g, _c, target, rendered = await run_command(
        bot, "giverole", f"<@{BOT_ID}> giverole <@141414141414141414> ; verified | trusted", target_id=141414141414141414
    )
    check("giverole executes", any(call[0] == "add_roles" for call in target.calls), f"calls={target.calls}")

    _g, _c, _t, rendered = await run_command(
        bot, "giverole without role", f"<@{BOT_ID}> giverole <@151515151515151515>", target_id=151515151515151515
    )
    check("giverole without role is refused", "Provide role" in rendered, rendered)

    # 6. Nickname operations.
    _g, _c, target, rendered = await run_command(
        bot, "locknick", f"<@{BOT_ID}> locknick <@161616161616161616> ; Watchful", target_id=161616161616161616
    )
    check("locknick edits nickname", any(call[0] == "edit" for call in target.calls), f"calls={target.calls}")

    # 7. Anti-Nuke module gating + status.
    _g, _c, _t, rendered = await run_command(bot, "antinuke status while disabled", f"<@{BOT_ID}> antinuke status")
    check("disabled anti_nuke module silent", not rendered.strip(), rendered)

    _g, _c, _t, rendered = await run_command(bot, "module active anti_nuke", f"<@{BOT_ID}> module active anti_nuke")
    check("anti_nuke module active", guild_cfg()["modules"].get("anti_nuke") == "active", str(guild_cfg()["modules"]))

    _g, _c, _t, rendered = await run_command(bot, "antinuke status", f"<@{BOT_ID}> antinuke status")
    check("antinuke status shows DISABLED", "DISABLED" in rendered, rendered)

    _g, _c, _t, rendered = await run_command(bot, "antinuke enable enforcement", f"<@{BOT_ID}> antinuke enable enforcement")
    check(
        "antinuke enable enforcement",
        guild_cfg()["anti_nuke"]["enabled"] is True and guild_cfg()["anti_nuke"]["mode"] == "enforcement",
        str(guild_cfg()["anti_nuke"])[:120],
    )

    _g, _c, _t, rendered = await run_command(bot, "antinuke whitelist list", f"<@{BOT_ID}> antinuke whitelist list")
    check("antinuke allowlist shows hardcoded owner", "708390973712891976" in rendered, rendered)

    # 8. Diagnostics + help surfaces.
    for keyword in ("health", "config", "whoami", "shorehelp", "ping"):
        _g, _c, _t, rendered = await run_command(bot, f"core {keyword}", f"<@{BOT_ID}> {keyword}")
        check(f"core command {keyword} responds", rendered not in ("", "(nothing)"), rendered[:90])


async def go():
    bot = await boot()
    await scenarios(bot)
    print()
    failed = [name for name, ok, _detail in RESULTS if not ok]
    print(f"TOTAL={len(RESULTS)} FAILED={len(failed)}")
    for name in failed:
        print("  FAILED:", name)
    return 0 if not failed else 1


sys.exit(asyncio.run(go()))