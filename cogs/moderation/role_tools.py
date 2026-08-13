import re

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, immunity_reason, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger


ROLE_ID_RE = re.compile(r"\d{17,20}")


class RoleToolsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def resolve_role(self, guild: discord.Guild, raw: str):
        if not raw:
            return None
        match = ROLE_ID_RE.search(raw)
        if match:
            return guild.get_role(int(match.group()))
        lowered = raw.strip().lower()
        for role in guild.roles:
            if role.name.lower() == lowered:
                return role
        return None

    async def send_role_log(self, guild, action, moderator, target, role, reason):
        mod_logs_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(mod_logs_id) if mod_logs_id else None
        if not channel:
            return
        embed = discord.Embed(title=f"Role Action: {action}", color=0xF1C40F)
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Role", value=f"{role.mention} ({role.id})" if role else "Not applied", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return
        if message.author.bot or not message.guild:
            return

        keyword = trigger["keyword"]
        if keyword not in {"giverole", "removerole"}:
            return

        if not is_mod(message.author):
            return await message.channel.send("No permission.")

        target = trigger["target"]
        if not target:
            return await message.channel.send(f"Use `@Shorekeeper {keyword} @user ; role_name_or_id | optional reason`.")
        protected = immunity_reason(target, keyword)
        if protected:
            await self.send_role_log(message.guild, f"Blocked {keyword}", message.author, target, None, protected)
            return await message.channel.send(protected)

        extra = (trigger["extra"] or "").strip()
        if not extra:
            return await message.channel.send("Provide role name or role ID after `;`.")

        parts = [p.strip() for p in extra.split("|", 1)]
        role = self.resolve_role(message.guild, parts[0])
        reason = parts[1] if len(parts) > 1 and parts[1] else "No reason."
        if not role:
            return await message.channel.send("Role not found. Use exact role name or ID.")

        if role >= message.author.top_role and message.author != message.guild.owner:
            return await message.channel.send("You cannot manage a role equal/higher than your top role.")

        if role >= message.guild.me.top_role:
            return await message.channel.send("My role is too low to manage that role.")

        try:
            if keyword == "giverole":
                await target.add_roles(role, reason=reason)
                await self.send_role_log(message.guild, "Give Role", message.author, target, role, reason)
                return await message.channel.send(f"Gave {role.mention} to {target.mention}.")
            await target.remove_roles(role, reason=reason)
            await self.send_role_log(message.guild, "Remove Role", message.author, target, role, reason)
            return await message.channel.send(f"Removed {role.mention} from {target.mention}.")
        except Exception as exc:
            await message.channel.send(f"Role action failed: {exc}")


async def setup(bot):
    await bot.add_cog(RoleToolsCog(bot))
