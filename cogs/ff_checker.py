import json
import os
import re

import discord
from discord.ext import commands

from cogs.server_config import is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


RULES_PATH = "config/ff_rules.json"
MAX_BYTES = 256 * 1024


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f).setdefault("categories", {})


def save_rules(categories):
    os.makedirs(os.path.dirname(RULES_PATH), exist_ok=True)
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump({"categories": categories}, f, indent=2)


def strip_comments(text):
    cleaned = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if "//" in stripped:
            stripped = stripped.split("//", 1)[0].strip()
        cleaned.append(stripped)
    return "\n".join(cleaned)


def parse_flags(filename, text):
    cleaned = strip_comments(text)
    lowered = filename.lower()
    if lowered.endswith(".json") or lowered == "clientappsettings.json":
        payload = json.loads(cleaned or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object.")
        return {str(key): value for key, value in payload.items()}

    flags = {}
    for line in cleaned.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            key, value = line, ""
        key = key.strip().strip('"')
        if key:
            flags[key] = value.strip().strip('",')
    return flags


def _matches_any(value, patterns):
    return any(re.fullmatch(pattern, value, flags=re.IGNORECASE) for pattern in patterns)


def classify_flags(flags, categories):
    safe_prefixes = tuple(prefix.lower() for prefix in categories.get("safe_prefixes", []))
    review_prefixes = tuple(prefix.lower() for prefix in categories.get("review_prefixes", []))
    warning_patterns = categories.get("warning_patterns", [])
    allowed_patterns = categories.get("allowed_patterns", [])
    review_patterns = categories.get("review_patterns", [])

    counts = {"safe": 0, "warning": 0, "review": 0, "unsupported": 0}
    notes = []
    samples = {"warning": [], "review": [], "unsupported": []}

    for flag in flags:
        lowered = flag.lower()
        if _matches_any(flag, review_patterns) or lowered.startswith(review_prefixes):
            counts["review"] += 1
            samples["review"].append(flag)
        elif _matches_any(flag, warning_patterns):
            counts["warning"] += 1
            samples["warning"].append(flag)
        elif _matches_any(flag, allowed_patterns) or lowered.startswith(safe_prefixes):
            counts["safe"] += 1
        elif re.search(r"(internal|version|v\d+$)", flag, flags=re.IGNORECASE):
            counts["unsupported"] += 1
            samples["unsupported"].append(flag)
        else:
            counts["warning"] += 1
            samples["warning"].append(flag)

    if len(flags) > 100:
        counts["warning"] += 1
        notes.append("Excessive flag count over 100.")
    if counts["review"]:
        status = "REVIEW"
        notes.append("One or more flags match gameplay-alteration review categories.")
    elif counts["unsupported"]:
        status = "UNSUPPORTED"
        notes.append("Some flags look versioned/internal or are not recognised.")
    elif counts["warning"]:
        status = "WARNING"
        notes.append("Unknown, deprecated, or risky-looking flags were found.")
    else:
        status = "SAFE"
        notes.append("Only empty/default, graphics, FPS, UI, telemetry, or allowed flags were found.")

    return status, counts, notes, samples


class FastFlagChecker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return
        if trigger["keyword"] == "ffcheck":
            return await self._check(message)
        if trigger["keyword"] == "ff":
            return await self._admin_rule(message, trigger)

    async def _check(self, message):
        if not message.attachments:
            return await message.channel.send("Attach a `.txt`, `.json`, or `ClientAppSettings.json` file.")
        attachment = message.attachments[0]
        name = attachment.filename
        lowered = name.lower()
        if not (lowered.endswith(".txt") or lowered.endswith(".json") or lowered == "clientappsettings.json"):
            return await message.channel.send("UNSUPPORTED: only `.txt`, `.json`, and `ClientAppSettings.json` are accepted.")
        if attachment.size and attachment.size > MAX_BYTES:
            return await message.channel.send("UNSUPPORTED: file is too large for review.")

        try:
            raw = await attachment.read()
            text = raw.decode("utf-8-sig", errors="replace")
            flags = parse_flags(name, text)
            status, counts, notes, samples = classify_flags(flags, load_rules())
        except Exception as exc:
            return await message.channel.send(f"UNSUPPORTED: could not parse file (`{type(exc).__name__}: {exc}`).")

        embed = discord.Embed(title="FastFlag Report", color=self._color(status))
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Flags", value=f"safe_count: `{counts['safe']}`\nwarning_count: `{counts['warning']}`\nreview_count: `{counts['review']}`", inline=False)
        embed.add_field(name="Notes", value="\n".join(notes), inline=False)
        for key in ("warning", "review", "unsupported"):
            if samples[key]:
                embed.add_field(name=f"{key.title()} Samples", value="\n".join(samples[key][:8])[:1024], inline=False)
        embed.set_footer(text="Classification only. This does not detect cheats and does not punish users.")
        await message.channel.send(embed=embed)

    async def _admin_rule(self, message, trigger):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        args = trigger["args"]
        if len(args) < 2 or args[0].lower() not in {"allow", "warn", "review"}:
            return await message.channel.send("Use `ff allow <pattern>`, `ff warn <pattern>`, or `ff review <pattern>`.")
        mode = args[0].lower()
        pattern = " ".join(args[1:]).strip()
        categories = load_rules()
        key = {"allow": "allowed_patterns", "warn": "warning_patterns", "review": "review_patterns"}[mode]
        categories.setdefault(key, [])
        try:
            re.compile(pattern)
        except re.error as exc:
            return await message.channel.send(f"Invalid regex: `{exc}`")
        if pattern not in categories[key]:
            categories[key].append(pattern)
            save_rules(categories)
        await message.channel.send(f"FastFlag rule added to `{key}`: `{pattern}`")

    def _color(self, status):
        return {
            "SAFE": 0x57F287,
            "WARNING": 0xFEE75C,
            "UNSUPPORTED": 0x95A5A6,
            "REVIEW": 0xED4245,
        }.get(status, 0x95A5A6)


async def setup(bot):
    await bot.add_cog(FastFlagChecker(bot))
