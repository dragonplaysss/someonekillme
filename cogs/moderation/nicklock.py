import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.responses import response_engine
from cogs.mongo_client import get_mongo_database, safe_create_index
from cogs.server_config import get_channel_id, get_guild_config, immunity_reason, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class NickLockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.nick_locks = self.db["nick_locks"]

    async def cog_load(self):
        await safe_create_index(self.nick_locks, [("guild_id", 1), ("user_id", 1)], unique=True)

    async def send_log(self, guild, action, moderator, target, details):
        mod_logs_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(mod_logs_id) if mod_logs_id else None
        if not channel:
            return
        embed = response_engine.build(
            title=f"NickLock: {action}",
            description="",
            color=0x3498DB
        )
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Details", value=details, inline=False)
        await channel.send(embed=embed)

    def authorize_nickname_action(self, message, target):
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.author,
                bot_member=bot_member,
                target_member=target,
                target_role=None,
                actor_authorized=is_admin(message.author),
                required_bot_permissions=("manage_nicknames",),
                required_actor_permissions=("manage_nicknames",),
                security_policy_allowed=True,
                security_action="manage_nickname",
            )
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick == after.nick:
            return

        lock = await self.nick_locks.find_one({"guild_id": after.guild.id, "user_id": after.id})
        if not lock:
            return
        if immunity_reason(after, "nicklock"):
            await self.nick_locks.delete_one({"guild_id": after.guild.id, "user_id": after.id})
            return

        locked_nick = lock.get("nick")
        if after.nick == locked_nick:
            return
        try:
            await after.edit(nick=locked_nick, reason="Nickname is locked by Shorekeeper.")
        except Exception as exc:
            print(f"[NICKLOCK] Failed enforcing nick lock: {type(exc).__name__}: {exc}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return
        if message.author.bot or not message.guild:
            return

        keyword = trigger["keyword"]
        target = trigger["target"]
        extra = trigger["extra"]

        if keyword == "locknick":
            if not is_admin(message.author):
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper locknick @user ; nickname`."
                )
                await message.channel.send(embed=embed)
                return
            protected = immunity_reason(target, "nicklock")
            if protected:
                await self.send_log(message.guild, "Blocked Lock", message.author, target, protected)
                embed = response_engine.failure(
                    title="Action Blocked",
                    description=protected
                )
                await message.channel.send(embed=embed)
                return
            new_nick = (extra or "").strip()
            if not new_nick:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Provide nickname after `;`."
                )
                await message.channel.send(embed=embed)
                return
            if len(new_nick) > 32:
                embed = response_engine.failure(
                    title="Invalid Nickname",
                    description="Nickname must be <= 32 characters."
                )
                await message.channel.send(embed=embed)
                return

            decision = self.authorize_nickname_action(message, target)
            if not decision.allowed:
                embed = response_engine.permission_denied(
                    detail=decision.reason or "Action denied by Shorekeeper's safety checks."
                )
                await message.channel.send(embed=embed)
                return

            await self.nick_locks.update_one(
                {"guild_id": message.guild.id, "user_id": target.id},
                {
                    "$set": {
                        "nick": new_nick,
                        "locked_by": message.author.id,
                        "updated_at": discord.utils.utcnow(),
                    }
                },
                upsert=True,
            )
            try:
                await target.edit(nick=new_nick, reason=f"Nickname locked by {message.author}")
            except Exception as exc:
                embed = response_engine.failure(
                    title="Nick Lock Applied Failed",
                    description=f"Nick lock saved, but applying failed: {exc}"
                )
                await message.channel.send(embed=embed)
                return

            await self.send_log(message.guild, "Lock", message.author, target, f"Locked as `{new_nick}`")
            embed = response_engine.success(
                title="Nickname Locked",
                description=f"Nickname locked for {target.mention} as `{new_nick}`."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "unlocknick":
            if not is_admin(message.author):
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper unlocknick @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            decision = self.authorize_nickname_action(message, target)
            if not decision.allowed:
                embed = response_engine.permission_denied(
                    detail=decision.reason or "Action denied by Shorekeeper's safety checks."
                )
                await message.channel.send(embed=embed)
                return

            result = await self.nick_locks.delete_one({"guild_id": message.guild.id, "user_id": target.id})
            if result.deleted_count == 0:
                embed = response_engine.failure(
                    title="No Nick Lock Found",
                    description="That user has no nick lock."
                )
                await message.channel.send(embed=embed)
                return

            try:
                await target.edit(nick=None, reason=f"Nickname unlocked by {message.author}")
            except Exception:
                pass

            reason = extra or "No reason."
            await self.send_log(message.guild, "Unlock", message.author, target, reason)
            embed = response_engine.success(
                title="Nickname Unlocked",
                description=f"Nickname unlocked for {target.mention}."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "nicklocks":
            if not is_admin(message.author):
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            docs = (
                await self.nick_locks.find({"guild_id": message.guild.id}).sort("updated_at", -1).limit(20).to_list(20)
            )
            if not docs:
                embed = response_engine.info(
                    title="Nick Locks Status",
                    description="No nick locks are active."
                )
                await message.channel.send(embed=embed)
                return
            lines = []
            for doc in docs:
                user = message.guild.get_member(doc["user_id"])
                label = user.mention if user else f"<@{doc['user_id']}>"
                lines.append(f"- {label} -> `{doc.get('nick', 'Unknown')}`")
            embed = response_engine.build(
                title="Active Nick Locks",
                description="\n".join(lines),
                color=0x3498DB
            )
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(NickLockCog(bot))