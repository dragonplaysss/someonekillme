import re

import discord
from discord.ext import commands

from cogs.server_config import is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] not in {"giverole", "removerole"}:
            return
        if self.bot.get_cog("RoleToolsCog"):
            return

        if not is_admin(message.author):
            return await message.channel.send("Nice try, get perms.")

        target = trigger["target"]
        if not target:
            return await message.channel.send("Mention a user.")

        try:
            role_ids = [
                int(match)
                for match in re.findall(r"\d{17,20}", trigger["main"])
                if int(match) != target.id
            ]
            if not role_ids:
                return await message.channel.send("Need a role ID.")

            role = message.guild.get_role(role_ids[-1])
            if not role:
                return await message.channel.send("Role not found.")

            reason = trigger["extra"] or None
            if trigger["keyword"] == "removerole":
                await target.remove_roles(role, reason=reason)
                await message.channel.send(f"Removed {role.name}")
            else:
                await target.add_roles(role, reason=reason)
                await message.channel.send(f"Gave {role.name}")
        except discord.Forbidden:
            await message.channel.send("Hierarchy error: put my role higher.")
        except Exception as e:
            await message.channel.send(f"Role update failed: {e}")


async def setup(bot):
    await bot.add_cog(Roles(bot))
