import re

import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.responses import response_engine
from cogs.server_config import get_guild_config, immunity_reason, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def authorize_role_action(self, message, action, target, role, actor_authorized):
        """Legacy giverole/removerole path routed through the central pipeline."""
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.author,
                bot_member=bot_member,
                target_member=target,
                target_role=role,
                actor_authorized=actor_authorized,
                required_bot_permissions=("manage_roles",),
                required_actor_permissions=("manage_roles",),
                security_policy_allowed=True,
                security_action=action,
            )
        )

    async def deny(self, message, decision):
        detail = decision.reason or "Action denied by Shorekeeper's safety checks."
        if decision.stage.endswith("hierarchy"):
            return await message.channel.send(embed=response_engine.hierarchy_denied(detail))
        return await message.channel.send(embed=response_engine.permission_denied(detail))

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] not in {"giverole", "removerole"}:
            return
        if self.bot.get_cog("RoleToolsCog"):
            return

        if not is_admin(message.author):
            embed = response_engine.permission_denied(
                detail="Nice try, get perms."
            )
            await message.channel.send(embed=embed)
            return

        target = trigger["target"]
        if not target:
            embed = response_engine.failure(
                title="Missing Argument",
                description="Mention a user."
            )
            await message.channel.send(embed=embed)
            return

        protected = immunity_reason(target, trigger["keyword"])
        if protected:
            embed = response_engine.failure(
                title="Action Denied",
                description=protected
            )
            await message.channel.send(embed=embed)
            return

        try:
            role_ids = [
                int(match)
                for match in re.findall(r"\d{17,20}", trigger["main"])
                if int(match) != target.id
            ]
            if not role_ids:
                embed = response_engine.failure(
                    title="Missing Role ID",
                    description="Need a role ID."
                )
                await message.channel.send(embed=embed)
                return

            role = message.guild.get_role(role_ids[-1])
            if not role:
                embed = response_engine.failure(
                    title="Role Not Found",
                    description="Role not found."
                )
                await message.channel.send(embed=embed)
                return

            decision = self.authorize_role_action(
                message,
                trigger["keyword"],
                target,
                role,
                is_admin(message.author),
            )
            if not decision.allowed:
                return await self.deny(message, decision)

            reason = trigger["extra"] or None
            if trigger["keyword"] == "removerole":
                await target.remove_roles(role, reason=reason)
                embed = response_engine.success(
                    title="Role Removed",
                    description=f"Removed {role.name}"
                )
                await message.channel.send(embed=embed)
            else:
                await target.add_roles(role, reason=reason)
                embed = response_engine.success(
                    title="Role Given",
                    description=f"Gave {role.name}"
                )
                await message.channel.send(embed=embed)
        except discord.Forbidden:
            embed = response_engine.failure(
                title="Hierarchy Error",
                description="Hierarchy error: put my role higher."
            )
            await message.channel.send(embed=embed)
        except Exception as e:
            embed = response_engine.failure(
                title="Role Update Failed",
                description=f"Role update failed: {e}"
            )
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Roles(bot))