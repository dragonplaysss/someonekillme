from __future__ import annotations

import datetime
import re
import shlex
from dataclasses import dataclass, field

from cogs.core.permissions import guild_enabled, is_owner_id
from cogs.module_registry import get_module_state, module_for_mention, normalize_mention_keyword
from cogs.server_config import get_guild_config


USER_ID_RE = re.compile(r"\d{17,20}")
USER_MENTION_RE = re.compile(r"<@!?(\d{17,20})>")
BOT_MENTION_RE = re.compile(r"^<@!?(\d+)>$")
CHANNEL_MENTION_RE = re.compile(r"<#(\d{17,20})>")
ROLE_MENTION_RE = re.compile(r"<@&(\d{17,20})>")
DURATION_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[smhd])$", re.IGNORECASE)

OWNER_BYPASS_KEYWORDS = {
    "guild",
    "antinuke",
    "lockdown",
    "module",
    "resync",
    "health",
    "shorehelp",
    "ping",
    "whoami",
    "config",
    "showconfig",
    "verifyconfig",
}

INACTIVE_KEYWORD = "__inactive__"


@dataclass
class ParsedCommand:
    keyword: str
    raw_keyword: str
    module: str | None
    main: str
    args: list[str]
    extra: str
    target: object | None = None
    target_id: int | None = None
    channel: object | None = None
    channel_id: int | None = None
    role: object | None = None
    role_id: int | None = None
    duration_token: str | None = None
    error: str | None = None
    user_ids: list[int] = field(default_factory=list)
    extra_fields: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = {
            "keyword": self.keyword,
            "raw_keyword": self.raw_keyword,
            "module": self.module,
            "main": self.main,
            "args": self.args,
            "extra": self.extra,
            "target": self.target,
            "target_id": self.target_id,
            "user_ids": self.user_ids,
            "channel": self.channel,
            "channel_id": self.channel_id,
            "role": self.role,
            "role_id": self.role_id,
            "duration": self.duration_token,
            "error": self.error,
        }
        payload.update(self.extra_fields)
        return payload


def _debug(enabled, reason, **fields):
    if not enabled:
        return
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[TRIGGER PARSER] {reason}" + (f" {details}" if details else ""))


def tokenize_command_text(text: str) -> list[str]:
    if not text:
        return []
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def parse_duration_token(token: str | None):
    if not token:
        return None
    match = DURATION_RE.match(token.strip())
    if not match:
        return None
    amount = int(match.group("amount"))
    unit = match.group("unit").lower()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return amount * multipliers[unit]


def parse_duration(token: str | None) -> datetime.timedelta | None:
    """Parse a duration token such as `10m` into a timedelta."""
    seconds = parse_duration_token(token)
    if seconds is None:
        return None
    return datetime.timedelta(seconds=seconds)


def extract_user_ids(text: str | None, mentions=None) -> list[int]:
    """Collect user ids from mention objects and raw text, in order, without duplicates."""
    ids: list[int] = []
    for match in USER_MENTION_RE.finditer(text or ""):
        value = int(match.group(1))
        if value not in ids:
            ids.append(value)
    for member in mentions or []:
        value = getattr(member, "id", None)
        if value is None:
            continue
        value = int(value)
        if value not in ids:
            ids.append(value)
    if not ids:
        raw = USER_ID_RE.search(text or "")
        if raw:
            ids.append(int(raw.group()))
    return ids


def _is_bot_mention(token: str | None, bot_user_id) -> bool:
    match = BOT_MENTION_RE.match((token or "").strip())
    if not match:
        return False
    return str(bot_user_id) == match.group(1)


def parse_mention_command(bot_user_id, content, mentions=None) -> ParsedCommand | None:
    """Parse a mention-first command without touching guild state.

    Returns a `ParsedCommand` with the normalized keyword, shlex-split args and
    every user id referenced. Returns `None` when the message is not a mention
    command or carries no keyword. Module activation checks stay in
    `parse_shorekeeper_trigger()` so this stays a pure parsing primitive.
    """
    text = (content or "").strip()
    if not text:
        return None

    main, separator, extra_text = text.partition(";")
    tokens = tokenize_command_text(main.strip())
    if not tokens:
        return None
    if not _is_bot_mention(tokens[0], bot_user_id):
        return None

    tokens = tokens[1:]
    if not tokens:
        return None

    raw_keyword = tokens[0].lower()
    keyword = normalize_mention_keyword(raw_keyword)
    args = tokens[1:]

    user_ids = [
        value
        for value in extract_user_ids(text, mentions)
        if str(value) != str(bot_user_id)
    ]

    return ParsedCommand(
        keyword=keyword,
        raw_keyword=raw_keyword,
        module=module_for_mention(keyword),
        main=" ".join(tokens),
        args=args,
        extra=extra_text.strip() if separator else "",
        target_id=user_ids[0] if user_ids else None,
        user_ids=user_ids,
    )


def _first_id(regex: re.Pattern, text: str) -> int | None:
    match = regex.search(text or "")
    return int(match.group(1)) if match else None


def parse_shorekeeper_trigger(bot, message, debug=False):
    if getattr(message.author, "bot", False) or not getattr(message, "guild", None):
        _debug(
            debug,
            "ignored non-guild/bot message",
            author=getattr(message.author, "id", None),
            bot=getattr(message.author, "bot", None),
            guild=getattr(message.guild, "id", None),
        )
        return None

    if not bot.user or not bot.user.mentioned_in(message):
        _debug(
            debug,
            "bot mention not detected",
            bot_user=getattr(bot.user, "id", None),
            mentions=[getattr(user, "id", None) for user in getattr(message, "mentions", [])],
        )
        return None

    bot_mentions = {
        f"<@{bot.user.id}>",
        f"<@!{bot.user.id}>",
    }

    raw_content = (message.content or "").strip()
    if not raw_content:
        _debug(debug, "empty message content")
        return None

    parts = raw_content.split(None, 1)
    if not parts or parts[0] not in bot_mentions:
        _debug(debug, "mention is not first token", first_token=parts[0] if parts else None)
        return None

    command_text = parts[1].strip() if len(parts) > 1 else ""
    main, sep, extra = command_text.partition(";")
    tokens = tokenize_command_text(main.strip())
    main_parts = main.strip().split()

    if not tokens:
        _debug(debug, "missing command keyword")
        return None

    raw_keyword = tokens[0].lower()
    keyword = normalize_mention_keyword(raw_keyword)
    module = module_for_mention(keyword)
    args = tokens[1:]
    extra_text = extra.strip() if sep else ""
    guild_config = get_guild_config(message.guild.id)

    # Apply global guild activation check only for non-special modules
    if module not in ("roblox_auth", "roblox_snipe"):
        if not guild_enabled(guild_config):
            owner = is_owner_id(getattr(message.author, "id", None))
            if not owner or keyword not in OWNER_BYPASS_KEYWORDS:
                if not owner:
                    return ParsedCommand(
                        keyword=INACTIVE_KEYWORD,
                        raw_keyword=raw_keyword,
                        module="core",
                        main=main.strip(),
                        args=args,
                        extra=extra_text,
                        error="guild_inactive",
                    ).as_dict()
                if keyword not in OWNER_BYPASS_KEYWORDS:
                    return ParsedCommand(
                        keyword=INACTIVE_KEYWORD,
                        raw_keyword=raw_keyword,
                        module="core",
                        main=main.strip(),
                        args=args,
                        extra=extra_text,
                        error="guild_inactive",
                    ).as_dict()

    if module:
        state = get_module_state(guild_config, module)
        if state == "disabled":
            # Allow certain anti-nuke commands to work even when module is disabled
            anti_nuke_allowed_when_disabled = {"status", "show", "enable", "on", "disable", "off", "mode"}
            # Also allow roblox_auth and roblox_snipe to proceed so their cogs can handle authorization
            if module == "anti_nuke" and args and args[0].lower() in anti_nuke_allowed_when_disabled:
                pass  # Allow the command to proceed
            elif module in ("roblox_auth", "roblox_snipe"):
                pass  # Allow the command to proceed to let the cog handle the error
            else:
                _debug(debug, "module disabled", module=module, guild=message.guild.id)
                return None
        if state == "debug":
            print(
                f"[MODULE DEBUG] guild={message.guild.id} module={module} "
                f"keyword={raw_keyword}->{keyword} author={message.author.id}"
            )
    else:
        _debug(debug, "no module registered for keyword", keyword=keyword)

    target = None
    target_id = None
    for member in getattr(message, "mentions", []) or []:
        if getattr(member, "id", None) == getattr(bot.user, "id", None):
            continue
        target = member
        target_id = member.id
        break

    haystack = f"{main} {extra_text}"
    if target_id is None:
        mention_id = _first_id(USER_MENTION_RE, haystack)
        raw_id = mention_id or (int(USER_ID_RE.search(haystack).group()) if USER_ID_RE.search(haystack) else None)
        if raw_id and raw_id != getattr(bot.user, "id", None):
            target_id = raw_id
            target = message.guild.get_member(target_id)

    channel = None
    channel_id = None
    channel_mentions = list(getattr(message, "channel_mentions", []) or [])
    if channel_mentions:
        channel = channel_mentions[0]
        channel_id = channel.id
    else:
        channel_id = _first_id(CHANNEL_MENTION_RE, haystack)
        if channel_id:
            channel = message.guild.get_channel(channel_id)
        else:
            for token in args:
                if USER_ID_RE.fullmatch(token) and message.guild.get_channel(int(token)):
                    channel_id = int(token)
                    channel = message.guild.get_channel(channel_id)
                    break

    role = None
    role_id = _first_id(ROLE_MENTION_RE, haystack)
    role_mentions = list(getattr(message, "role_mentions", []) or [])
    if role_mentions:
        role = role_mentions[0]
        role_id = role.id
    elif role_id:
        role = message.guild.get_role(role_id)
    else:
        for token in args:
            if USER_ID_RE.fullmatch(token):
                maybe_role = message.guild.get_role(int(token))
                if maybe_role:
                    role = maybe_role
                    role_id = maybe_role.id
                    break

    duration_token = next((token for token in args if parse_duration_token(token) is not None), None)

    parsed = ParsedCommand(
        keyword=keyword,
        raw_keyword=raw_keyword,
        module=module,
        main=main.strip(),
        args=args,
        extra=extra_text,
        target=target,
        target_id=target_id,
        channel=channel,
        channel_id=channel_id,
        role=role,
        role_id=role_id,
        duration_token=duration_token,
        user_ids=extract_user_ids(
            haystack,
            [member for member in (getattr(message, "mentions", []) or []) if getattr(member, "id", None) != getattr(bot.user, "id", None)],
        ) or ([target_id] if target_id else []),
    )
    _debug(debug, "parsed command", raw_keyword=raw_keyword, keyword=keyword, module=module)
    return parsed.as_dict()
