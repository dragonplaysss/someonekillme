import re


USER_ID_RE = re.compile(r"\d{17,20}")


def parse_shorekeeper_trigger(bot, message):
    if message.author.bot or not message.guild:
        return None

    if not bot.user or not bot.user.mentioned_in(message):
        return None

    bot_mentions = {
        f"<@{bot.user.id}>",
        f"<@!{bot.user.id}>",
    }

    raw_content = message.content.strip()
    parts = raw_content.split(None, 1)

    if not parts or parts[0] not in bot_mentions:
        return None

    command_text = parts[1].strip() if len(parts) > 1 else ""
    main, sep, extra = command_text.partition(";")
    main_parts = main.strip().split()

    if not main_parts:
        return None

    keyword = main_parts[0].lower()
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
        "main": main.strip(),
        "args": main_parts[1:],
        "extra": extra.strip() if sep else "",
        "target": target,
        "target_id": target_id,
    }
