from discord.ext import commands

from cogs.server_config import get_guild_config, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "verify":
            return

        cfg = get_guild_config(message.guild.id)
        staff_roles = set(cfg.get("verify_staff_roles", []))
        is_staff = is_admin(message.author) or any(
            role.id in staff_roles for role in message.author.roles
        )

        if not is_staff:
            return await message.channel.send("You do not have permission.")

        target = trigger["target"]
        if not target:
            return await message.channel.send("Mention a user to verify.")

        try:
            unverified_role_id = cfg.get("unverified_role")
            unverified_role = message.guild.get_role(unverified_role_id) if unverified_role_id else None
            if unverified_role and unverified_role in target.roles:
                await target.remove_roles(
                    unverified_role, reason=trigger["extra"] or None
                )

            roles_to_add = [
                message.guild.get_role(role_id)
                for role_id in cfg.get("verified_roles", [])
                if message.guild.get_role(role_id)
            ]

            if roles_to_add:
                await target.add_roles(*roles_to_add, reason=trigger["extra"] or None)

            await message.channel.send(f"Verified {target.mention}")
        except Exception as e:
            await message.channel.send(f"Verify failed: {e}")


async def setup(bot):
    await bot.add_cog(Verify(bot))
