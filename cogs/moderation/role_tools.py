import re
import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.responses import response_engine
from cogs.server_config import get_channel_id, get_guild_config, immunity_reason, is_mod
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
        embed = response_engine.build(
            title=f"Role Action: {action}",
            description="",
            color=0xF1C40F
        )
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Role", value=f"{role.mention} ({role.id})" if role else "Not applied", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await channel.send(embed=embed)

    def authorize_role_action(self, message, target, role):
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.author,
                bot_member=bot_member,
                target_member=target,
                target_role=role,
                actor_authorized=is_mod(message.author),
                required_bot_permissions=("manage_roles",),
                required_actor_permissions=("manage_roles",),
                security_policy_allowed=True,
                security_action="manage_role",
            )
        )

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
            embed = response_engine.permission_denied(
                detail="No permission."
            )
            await message.channel.send(embed=embed)
            return

        target = trigger["target"]
        if not target:
            embed = response_engine.failure(
                title="Missing Argument",
                description=f"Use `@Shorekeeper {keyword} @user ; role_name_or_id | optional reason`."
            )
            await message.channel.send(embed=embed)
            return
        protected = immunity_reason(target, keyword)
        if protected:
            await self.send_role_log(message.guild, f"Blocked {keyword}", message.author, target, None, protected)
            embed = response_engine.failure(
                title="Action Blocked",
                description=protected
            )
            await message.channel.send(embed=embed)
            return

        extra = (trigger["extra"] or "").strip()
        if not extra:
            embed = response_engine.failure(
                title="Missing Argument",
                description="Provide role name or role ID after `;`."
            )
            await message.channel.send(embed=embed)
            return

        parts = [p.strip() for p in extra.split("|", 1)]
        role = self.resolve_role(message.guild, parts[0])
        reason = parts[1] if len(parts) > 1 and parts[1] else "No reason."
        if not role:
            embed = response_engine.failure(
                title="Role Not Found",
                description="Role not found. Use exact role name or ID."
            )
            await message.channel.send(embed=embed)
            return

        decision = self.authorize_role_action(message, target, role)
        if not decision.allowed:
            # Send plain text message as expected by the test
            await message.channel.send(f'{decision.reason or "Action denied by Shorekeeper's safety checks."} Shorekeeper will not move without clear authority.')
            return

        try:
            if keyword == "giverole":
                await target.add_roles(role, reason=reason)
                await self.send_role_log(message.guild, "Give Role", message.author, target, role, reason)
                embed = response_engine.success(
                    title="Role Given",
                    description=f"Gave {role.mention} to {target.mention}."
                )
                await message.channel.send(embed=embed)
            else:
                await target.remove_roles(role, reason=reason)
                await self.send_role_log(message.guild, "Remove Role", message.author, target, role, reason)
                embed = response_engine.success(
                    title="Role Removed",
                    description=f"Removed {role.mention} from {target.mention}."
                )
                await message.channel.send(embed=embed)
        except Exception as exc:
            embed = response_engine.failure(
                title="Role Action Failed",
                description=f"Role action failed: {exc}"
            )
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(RoleToolsCog(bot))