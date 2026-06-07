import json
import os

import discord
from discord.ext import commands

from cogs.trigger_parser import parse_shorekeeper_trigger
from cogs.server_config import get_guild_config, is_admin, update_guild_config


DATA_FILE = "cogs/moderation/data2/seals.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class Seal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_seal_role(self, guild):
        guild_config = get_guild_config(guild.id)
        role = guild.get_role(guild_config.get("sealed_role") or 0)

        if not role:
            role = discord.utils.get(
                guild.roles,
                name="sealed"
            )

        if role:
            if guild_config.get("sealed_role") != role.id:
                update_guild_config(guild.id, lambda config: config.update({"sealed_role": role.id}))
            return role

        role = await guild.create_role(
            name="sealed"
        )
        update_guild_config(guild.id, lambda config: config.update({"sealed_role": role.id}))
        return role

    def get_bot_member(self, guild):
        return guild.me or guild.get_member(self.bot.user.id)

    def validate_can_manage_member(self, member):
        bot_member = self.get_bot_member(member.guild)

        if not bot_member:
            return "I could not find my member profile in this server."
        if member == member.guild.owner:
            return "I cannot change roles on the server owner."
        if not bot_member.guild_permissions.manage_roles:
            return "I need the Manage Roles permission."
        if member.top_role >= bot_member.top_role:
            return (
                "I cannot manage that member because their highest role is "
                "equal to or above my highest role."
            )
        return None

    def validate_can_use_role(self, guild, role):
        bot_member = self.get_bot_member(guild)

        if not bot_member:
            return "I could not find my member profile in this server."
        if role >= bot_member.top_role:
            return (
                f"I cannot assign or remove {role.mention} because it is "
                "equal to or above my highest role."
            )
        return None

    def get_guild_data(self, data, guild_id):
        guild_key = str(guild_id)
        guild_data = data.setdefault(guild_key, {})
        if not isinstance(guild_data, dict):
            guild_data = {}
            data[guild_key] = guild_data
        return guild_data

    async def seal_member(self, member):
        member_error = self.validate_can_manage_member(member)
        if member_error:
            return False, member_error

        seal_role = await self.get_seal_role(
            member.guild
        )
        role_error = self.validate_can_use_role(member.guild, seal_role)
        if role_error:
            return False, role_error

        saved_roles = [
            role.id
            for role in member.roles
            if role.name != "@everyone"
            and not role.managed
            and role != seal_role
        ]

        data = load_data()
        guild_data = self.get_guild_data(data, member.guild.id)

        await member.edit(
            roles=[seal_role],
            reason="Sealed by Shorekeeper",
        )

        guild_data[str(member.id)] = saved_roles
        if str(member.id) in data and isinstance(data[str(member.id)], list):
            del data[str(member.id)]
        save_data(data)
        return True, None

    async def unseal_member(self, member):
        member_error = self.validate_can_manage_member(member)
        if member_error:
            return False, member_error

        data = load_data()
        guild_data = self.get_guild_data(data, member.guild.id)

        saved_roles = guild_data.get(str(member.id))
        if saved_roles is None and isinstance(data.get(str(member.id)), list):
            saved_roles = data.get(str(member.id))

        if saved_roles is None:
            return False, "User is not sealed."

        restored_roles = []
        skipped_roles = []
        bot_member = self.get_bot_member(member.guild)

        for role_id in saved_roles:
            role = member.guild.get_role(role_id)

            if not role:
                continue
            if bot_member and role >= bot_member.top_role:
                skipped_roles.append(role.name)
                continue
            if not role.managed:
                restored_roles.append(role)

        await member.edit(
            roles=restored_roles,
            reason="Unsealed by Shorekeeper",
        )

        if str(member.id) in guild_data:
            del guild_data[str(member.id)]
        if str(member.id) in data and isinstance(data[str(member.id)], list):
            del data[str(member.id)]

        save_data(data)

        if skipped_roles:
            return True, "Skipped roles above me: " + ", ".join(skipped_roles)
        return True, None

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(
            self.bot,
            message,
        )

        if not trigger:
            return

        keyword = trigger["keyword"]

        if keyword not in {
            "seal",
            "unseal",
        }:
            return

        if not is_admin(message.author):
            return await message.channel.send(
                "No permission."
            )

        target = trigger["target"]

        if not target:
            return await message.channel.send(
                "User not found."
            )

        if keyword == "seal":
            try:
                success, detail = await self.seal_member(target)

                if not success:
                    return await message.channel.send(
                        f"Seal failed: {detail}"
                    )

                await message.channel.send(
                    f"{target.mention} has been sealed."
                )

            except Exception as e:
                await message.channel.send(
                    f"Seal failed: {e}"
                )

        if keyword == "unseal":
            success, detail = await self.unseal_member(
                target
            )

            if success:
                content = f"{target.mention} has been unsealed."
                if detail:
                    content += f" {detail}"
                await message.channel.send(content)
            else:
                await message.channel.send(
                    detail
                )


async def setup(bot):
    await bot.add_cog(Seal(bot))
