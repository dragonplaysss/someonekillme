import json
import os

import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.hierarchy import can_bot_manage_role
from cogs.core.persistence import atomic_write_json
from cogs.core.responses import response_engine
from cogs.trigger_parser import parse_shorekeeper_trigger
from cogs.server_config import get_channel_id, get_guild_config, immunity_reason, is_admin, is_mod, update_guild_config


DATA_FILE = "cogs/moderation/data2/seals.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    atomic_write_json(DATA_FILE, data)


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
        protected = immunity_reason(member, "seal")
        if protected:
            return protected
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

    async def send_security_log(self, guild, moderator, target, reason):
        channel_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return
        embed = response_engine.build(
            title="Security: Blocked Seal",
            description="",
            color=0xED4245
        )
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await channel.send(embed=embed)

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

        saved_roles = []
        blocked_roles = []
        bot_member = self.get_bot_member(member.guild)
        for role in member.roles:
            if role.name == "@everyone" or role.managed or role == seal_role:
                continue
            if bot_member is not None and not can_bot_manage_role(bot_member, role).allowed:
                blocked_roles.append(role.name)
                continue
            saved_roles.append(role.id)

        if blocked_roles:
            # Never attempt the API call: Discord's role order is absolute.
            return False, (
                "Shorekeeper cannot seal that member because these roles are equal to or above "
                "Shorekeeper's highest role: "
                + ", ".join(sorted(blocked_roles))
            )

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
            if bot_member is None or not can_bot_manage_role(bot_member, role).allowed:
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

        if not is_admin(message.author) and not is_mod(message.author):
            embed = response_engine.permission_denied(
                detail="No permission."
            )
            await message.channel.send(embed=embed)
            return

        target = trigger["target"]

        if not target:
            embed = response_engine.failure(
                title="User Not Found",
                description="User not found."
            )
            await message.channel.send(embed=embed)
            return

        decision = authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.author,
                bot_member=self.get_bot_member(message.guild),
                target_member=target,
                target_role=None,
                actor_authorized=is_admin(message.author),
                required_bot_permissions=("manage_roles",),
                required_actor_permissions=("manage_roles",),
                security_policy_allowed=True,
                security_action=keyword,
            )
        )
        if not decision.allowed:
            embed = response_engine.permission_denied(
                detail=decision.reason or "Action denied by Shorekeeper's safety checks."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "seal":
            try:
                success, detail = await self.seal_member(target)

                if not success:
                    if detail and "protected" in detail.lower():
                        await self.send_security_log(message.guild, message.author, target, detail)
                    embed = response_engine.failure(
                        title="Seal Failed",
                        description=f"Seal failed: {detail}"
                    )
                    await message.channel.send(embed=embed)
                    return

                embed = response_engine.success(
                    title="Member Sealed",
                    description=f"{target.mention} has been sealed."
                )
                await message.channel.send(embed=embed)

            except Exception as e:
                embed = response_engine.failure(
                    title="Seal Failed",
                    description=f"Seal failed: {e}"
                )
                await message.channel.send(embed=embed)

        if keyword == "unseal":
            success, detail = await self.unseal_member(
                target
            )

            if success:
                description = f"{target.mention} has been unsealed."
                if detail:
                    description += f" {detail}"
                embed = response_engine.success(
                    title="Member Unsealed",
                    description=description
                )
                await message.channel.send(embed=embed)
            else:
                embed = response_engine.failure(
                    title="Unseal Failed",
                    description=detail
                )
                await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Seal(bot))