from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.responses import response_engine
from cogs.server_config import get_guild_config, immunity_reason, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def authorize_role_action(self, message, action, target, role, actor_authorized):
        """Role changes during verification still respect the safety pipeline."""
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="verify",
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
        if not trigger or trigger["keyword"] != "verify":
            return

        cfg = get_guild_config(message.guild.id)
        staff_roles = set(cfg.get("verify_staff_roles", []))
        is_staff = is_admin(message.author) or any(
            role.id in staff_roles for role in message.author.roles
        )

        if not is_staff:
            embed = response_engine.permission_denied(
                detail="You do not have permission."
            )
            await message.channel.send(embed=embed)
            return

        target = trigger["target"]
        if not target:
            embed = response_engine.failure(
                title="Missing Argument",
                description="Mention a user to verify."
            )
            await message.channel.send(embed=embed)
            return

        protected = immunity_reason(target, "verify")
        if protected:
            embed = response_engine.failure(
                title="Action Denied",
                description=protected
            )
            await message.channel.send(embed=embed)
            return

        try:
            unverified_role_id = cfg.get("unverified_role")
            unverified_role = message.guild.get_role(unverified_role_id) if unverified_role_id else None
            if unverified_role and unverified_role in target.roles:
                decision = self.authorize_role_action(message, "verify", target, unverified_role, is_staff)
                if not decision.allowed:
                    return await self.deny(message, decision)
                await target.remove_roles(
                    unverified_role, reason=trigger["extra"] or None
                )

            roles_to_add = [
                message.guild.get_role(role_id)
                for role_id in cfg.get("verified_roles", [])
                if message.guild.get_role(role_id)
            ]

            for role in roles_to_add:
                decision = self.authorize_role_action(message, "verify", target, role, is_staff)
                if not decision.allowed:
                    return await self.deny(message, decision)

            if roles_to_add:
                await target.add_roles(*roles_to_add, reason=trigger["extra"] or None)

            embed = response_engine.success(
                title="Verification Successful",
                description=f"Verified {target.mention}"
            )
            await message.channel.send(embed=embed)
        except Exception as e:
            embed = response_engine.failure(
                title="Verification Failed",
                description=str(e)
            )
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Verify(bot))