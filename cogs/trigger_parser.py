import re

from cogs.module_registry import get_module_state, module_for_mention, normalize_mention_keyword
from cogs.server_config import get_guild_config


USER_ID_RE = re.compile(r"\d{17,20}")


def _debug(enabled, reason, **fields):
    if not enabled:
        return
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[TRIGGER PARSER] {reason}" + (f" {details}" if details else ""))


def parse_shorekeeper_trigger(bot, message, debug=False):
    if message.author.bot or not message.guild:
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

    _debug(debug, "mention detected", bot_user=bot.user.id)

    bot_mentions = {
        f"<@{bot.user.id}>",
        f"<@!{bot.user.id}>",
    }

    raw_content = message.content.strip()
    if not raw_content:
        _debug(
            debug,
            "empty message content",
            hint="Enable Message Content Intent in Discord Developer Portal and code.",
        )
        return None

    parts = raw_content.split(None, 1)

    if not parts or parts[0] not in bot_mentions:
        _debug(debug, "mention is not first token", first_token=parts[0] if parts else None)
        return None

    command_text = parts[1].strip() if len(parts) > 1 else ""
    main, sep, extra = command_text.partition(";")
    main_parts = main.strip().split()

    if not main_parts:
        _debug(debug, "missing command keyword")
        return None

    raw_keyword = main_parts[0].lower()
    keyword = normalize_mention_keyword(raw_keyword)
    module = module_for_mention(keyword)
    _debug(debug, "parsed command", raw_keyword=raw_keyword, keyword=keyword, module=module)
    if module:
        guild_config = get_guild_config(message.guild.id)
        state = get_module_state(guild_config, module)
        if state == "disabled":
            _debug(debug, "module disabled", module=module, guild=message.guild.id)
            return None
        if state == "debug":
            print(f"[MODULE DEBUG] guild={message.guild.id} module={module} keyword={raw_keyword}->{keyword} author={message.author.id}")
    else:
        _debug(debug, "no module registered for keyword", keyword=keyword)

    target_id = None
    target = None

    for member in message.mentions:
        if member != bot.user:
            target = member
            target_id = member.id
            break

    if target_id is None:
        match = USER_ID_RE.search(main)
        if match:
            target_id = int(match.group())
            target = message.guild.get_member(target_id)

    return {
        "keyword": keyword,
        "raw_keyword": raw_keyword,
        "module": module,
        "main": main.strip(),
        "args": main_parts[1:],
        "extra": extra.strip() if sep else "",
        "target": target,
        "target_id": target_id,
    }
