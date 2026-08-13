import asyncio
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.module_registry import get_module_state, set_module_state
from cogs.server_config import get_guild_config, is_admin, is_panel_owner, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=8)
USER_CACHE_TTL = 300
GAME_CACHE_TTL = 300
PRESENCE_CACHE_TTL = 8
MAX_CONCURRENT_SEARCHES = 4


@dataclass
class CacheEntry:
    value: object
    expires_at: float


@dataclass
class SnipeResult:
    username: str
    display_name: Optional[str] = None
    user_id: Optional[int] = None
    avatar_url: Optional[str] = None
    presence_type: Optional[int] = None
    last_location: Optional[str] = None
    place_id: Optional[int] = None
    universe_id: Optional[int] = None
    job_id: Optional[str] = None
    game_name: Optional[str] = None
    server_verified: bool = False
    server_status: str = "Unknown"
    error: Optional[str] = None
    search_seconds: float = 0.0


def _now() -> float:
    return time.monotonic()


def _discord_now():
    return discord.utils.utcnow()


def _presence_label(presence_type: Optional[int]) -> str:
    return {
        0: "Offline",
        1: "Online",
        2: "In Game",
        3: "In Studio",
    }.get(presence_type, "Unknown")


class SnipeJoinView(discord.ui.View):
    def __init__(self, cog: "RobloxSnipeCog", requester_id: int, username: str, result: SnipeResult):
        super().__init__(timeout=300)
        self.cog = cog
        self.requester_id = requester_id
        self.username = username
        self.last_refresh = 0.0

        if result.place_id and result.job_id:
            pc_url = f"https://www.roblox.com/games/{result.place_id}?gameInstanceId={quote(result.job_id)}"
            mobile_url = f"roblox://experiences/start?placeId={result.place_id}&gameInstanceId={quote(result.job_id)}"
            self.add_item(discord.ui.Button(label="PC Join", style=discord.ButtonStyle.link, url=pc_url))
            self.add_item(discord.ui.Button(label="Mobile Join", style=discord.ButtonStyle.link, url=mobile_url))
        elif result.place_id:
            self.add_item(discord.ui.Button(label="Game Page", style=discord.ButtonStyle.link, url=f"https://www.roblox.com/games/{result.place_id}"))

    @discord.ui.button(label="Refresh Target", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.can_refresh(interaction, self.requester_id):
            return
        if _now() - self.last_refresh < self.cog.cooldown_for(interaction.guild):
            return await interaction.response.send_message("Refresh is cooling down. Try again shortly.", ephemeral=True)
        self.last_refresh = _now()
        await interaction.response.defer()
        result = await self.cog.run_pipeline(self.username)
        embed = self.cog.build_result_embed(result)
        await interaction.edit_original_response(embed=embed, view=SnipeJoinView(self.cog, self.requester_id, self.username, result))


class RobloxSnipeCog(commands.Cog):
    snipeconfig = app_commands.Group(name="snipeconfig", description="Configure Roblox Snipe.")

    def __init__(self, bot):
        self.bot = bot
        self.user_cache: dict[str, CacheEntry] = {}
        self.game_cache: dict[int, CacheEntry] = {}
        self.presence_cache: dict[int, CacheEntry] = {}
        self.user_cooldowns: dict[int, float] = {}
        self.guild_cooldowns: dict[int, float] = {}
        self.roblox_backoff_until = 0.0
        self.search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

    def module_enabled(self, guild: Optional[discord.Guild]) -> bool:
        if not guild:
            return False
        return get_module_state(get_guild_config(guild.id), "roblox_snipe") in {"active", "debug"}

    def cooldown_for(self, guild: Optional[discord.Guild]) -> int:
        if not guild:
            return 20
        value = get_guild_config(guild.id).get("snipe_cooldown_seconds", 20)
        try:
            return max(5, min(300, int(value)))
        except (TypeError, ValueError):
            return 20

    def has_snipe_access(self, member) -> bool:
        if is_panel_owner(getattr(member, "id", 0)):
            return True
        guild = getattr(member, "guild", None)
        if not guild:
            return False
        role_id = get_guild_config(guild.id).get("snipe_role")
        if not role_id:
            return False
        return any(role.id == role_id for role in getattr(member, "roles", []))

    async def ensure_snipe_access(self, interaction: discord.Interaction) -> bool:
        if not self.module_enabled(interaction.guild):
            await interaction.response.send_message("Roblox Snipe is disabled in this server.", ephemeral=True)
            return False
        if not self.has_snipe_access(interaction.user):
            await interaction.response.send_message("No permission. Ask staff to configure or assign the Snipe Role.", ephemeral=True)
            return False
        return True

    async def ensure_config_access(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return False
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def can_refresh(self, interaction: discord.Interaction, requester_id: int) -> bool:
        if interaction.user.id == requester_id or is_panel_owner(interaction.user.id) or self.has_snipe_access(interaction.user):
            return True
        await interaction.response.send_message("No permission to refresh this snipe.", ephemeral=True)
        return False

    def _cached(self, cache: dict, key):
        entry = cache.get(key)
        if entry and entry.expires_at > _now():
            return entry.value
        cache.pop(key, None)
        return None

    def _store(self, cache: dict, key, value, ttl: int):
        cache[key] = CacheEntry(value=value, expires_at=_now() + ttl)
        return value

    async def request_json(self, method: str, url: str, **kwargs):
        if self.roblox_backoff_until > _now():
            raise RuntimeError("Roblox recently rate limited requests. Try again shortly.")
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = int(retry_after) if retry_after else 30
                    except ValueError:
                        delay = 30
                    self.roblox_backoff_until = _now() + max(10, min(120, delay))
                    raise RuntimeError("Roblox rate limited this request. Try again later.")
                if response.status >= 400:
                    raise RuntimeError(f"Roblox API returned HTTP {response.status}.")
                return await response.json()

    async def resolve_user(self, username: str):
        key = username.lower()
        cached = self._cached(self.user_cache, key)
        if cached:
            return cached
        payload = {"usernames": [username], "excludeBannedUsers": False}
        data = await self.request_json("POST", "https://users.roblox.com/v1/usernames/users", json=payload)
        users = data.get("data") or []
        if not users:
            return None
        user = users[0]
        return self._store(
            self.user_cache,
            key,
            {"id": int(user["id"]), "name": user.get("name") or username, "displayName": user.get("displayName")},
            USER_CACHE_TTL,
        )

    async def fetch_presence(self, user_id: int):
        cached = self._cached(self.presence_cache, user_id)
        if cached:
            return cached
        payload = {"userIds": [user_id]}
        data = await self.request_json("POST", "https://presence.roblox.com/v1/presence/users", json=payload)
        presences = data.get("userPresences") or []
        presence = presences[0] if presences else {}
        return self._store(self.presence_cache, user_id, presence, PRESENCE_CACHE_TTL)

    async def fetch_avatar(self, user_id: int):
        data = await self.request_json(
            "GET",
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false",
        )
        items = data.get("data") or []
        return items[0].get("imageUrl") if items else None

    async def fetch_game_info(self, universe_id: Optional[int]):
        if not universe_id:
            return None
        cached = self._cached(self.game_cache, universe_id)
        if cached:
            return cached
        data = await self.request_json("GET", f"https://games.roblox.com/v1/games?universeIds={universe_id}")
        games = data.get("data") or []
        game = games[0] if games else None
        return self._store(self.game_cache, universe_id, game, GAME_CACHE_TTL)

    async def verify_server(self, place_id: Optional[int], job_id: Optional[str]) -> tuple[bool, str]:
        if not place_id or not job_id:
            return False, "No public Job ID exposed by presence."
        cursor = None
        checked = 0
        while checked < 300:
            url = f"https://games.roblox.com/v1/games/{place_id}/servers/Public?sortOrder=Asc&limit=100"
            if cursor:
                url += f"&cursor={quote(cursor)}"
            data = await self.request_json("GET", url)
            for server in data.get("data") or []:
                checked += 1
                if server.get("id") == job_id:
                    return True, "Verified via Presence + Public Server List"
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
        return False, "Presence exposed Job ID, but public server list did not confirm it."

    async def run_pipeline(self, username: str) -> SnipeResult:
        start = _now()
        result = SnipeResult(username=username)
        try:
            user = await self.resolve_user(username)
            if not user:
                result.error = "User not found."
                return result
            result.user_id = user["id"]
            result.username = user["name"]
            result.display_name = user.get("displayName")
            presence, avatar = await asyncio.gather(
                self.fetch_presence(result.user_id),
                self.fetch_avatar(result.user_id),
                return_exceptions=True,
            )
            if isinstance(presence, Exception):
                raise presence
            if not isinstance(avatar, Exception):
                result.avatar_url = avatar
            result.presence_type = presence.get("userPresenceType")
            result.last_location = presence.get("lastLocation")
            result.place_id = presence.get("placeId") or presence.get("rootPlaceId")
            result.universe_id = presence.get("universeId")
            result.job_id = presence.get("gameId")

            if result.presence_type == 0:
                result.error = "Target is offline or no public presence is available."
                return result
            if result.presence_type != 2:
                result.error = f"Target is {_presence_label(result.presence_type).lower()}, not in a public game."
                return result

            try:
                game = await self.fetch_game_info(result.universe_id)
            except Exception as exc:
                print(f"[ROBLOX SNIPE] game metadata unavailable: {type(exc).__name__}: {exc}")
                game = None
            if game:
                result.game_name = game.get("name")

            if result.job_id:
                try:
                    result.server_verified, result.server_status = await self.verify_server(result.place_id, result.job_id)
                except Exception as exc:
                    print(f"[ROBLOX SNIPE] server verification unavailable: {type(exc).__name__}: {exc}")
                    result.server_verified = False
                    result.server_status = "Server discovery failed; Job ID was not confirmed."
            else:
                result.server_status = "Target is playing, but Roblox presence did not expose a Job ID."
            return result
        except asyncio.TimeoutError:
            result.error = "Roblox API timeout."
            return result
        except Exception as exc:
            print(f"[ROBLOX SNIPE] {type(exc).__name__}: {exc}")
            result.error = str(exc)[:160]
            return result
        finally:
            result.search_seconds = _now() - start

    def build_result_embed(self, result: SnipeResult) -> discord.Embed:
        if result.error:
            embed = discord.Embed(title="TARGET NOT FOUND", description=f"`{result.username}`: {result.error}", color=0xED4245, timestamp=_discord_now())
            embed.add_field(name="Search Time", value=f"`{result.search_seconds:.1f}s`", inline=True)
        elif result.server_verified:
            embed = discord.Embed(title="TARGET ACQUIRED: Direct Presence Match", color=0x57F287, timestamp=_discord_now())
        else:
            embed = discord.Embed(title="TARGET FOUND - SERVER UNVERIFIED", color=0xFEE75C, timestamp=_discord_now())
            embed.description = "Target is currently playing, but the active server instance could not be reliably confirmed."

        if result.user_id:
            embed.add_field(
                name="Target Info",
                value=f"Name: `{result.username}`\nDisplay: `@{result.display_name or result.username}`\nUser ID: `{result.user_id}`\nSearch Time: `{result.search_seconds:.1f}s`",
                inline=False,
            )
        if result.avatar_url:
            embed.set_thumbnail(url=result.avatar_url)
        if result.place_id or result.universe_id or result.game_name:
            embed.add_field(
                name="Game Information",
                value=f"Game: `{result.game_name or result.last_location or 'Unknown'}`\nPlace ID: `{result.place_id or 'Unknown'}`\nUniverse ID: `{result.universe_id or 'Unknown'}`",
                inline=False,
            )
        if result.job_id:
            embed.add_field(name="Verified Game Instance (Job ID)" if result.server_verified else "Presence Job ID", value=f"`{result.job_id}`", inline=False)
        embed.add_field(name="Server Region", value="Region: `Unknown / Region Locked`", inline=True)
        embed.add_field(name="Status", value=f"`{result.server_status}`", inline=False)
        embed.set_footer(text="Verified only with legitimate public Roblox APIs")
        return embed

    async def apply_rate_limit(self, member: discord.Member):
        cooldown = self.cooldown_for(member.guild)
        now = _now()
        user_ready = self.user_cooldowns.get(member.id, 0)
        guild_ready = self.guild_cooldowns.get(member.guild.id, 0)
        wait = max(user_ready - now, guild_ready - now, 0)
        if wait > 0:
            return int(wait) + 1
        self.user_cooldowns[member.id] = now + cooldown
        self.guild_cooldowns[member.guild.id] = now + max(3, cooldown // 2)
        return 0

    async def execute_snipe(self, destination, requester: discord.Member, username: str):
        if not USERNAME_RE.match(username or ""):
            return await destination.send("Invalid Roblox username. Use 3-20 letters, numbers, or underscores.")
        wait = await self.apply_rate_limit(requester)
        if wait:
            return await destination.send(f"Cooldown active. Try again in `{wait}s`.")
        async with self.search_semaphore:
            result = await self.run_pipeline(username)
        embed = self.build_result_embed(result)
        view = SnipeJoinView(self, requester.id, username, result)
        await destination.send(embed=embed, view=view)

    @app_commands.command(name="snipe", description="Locate a Roblox player's public game server when legitimately exposed.")
    async def snipe(self, interaction: discord.Interaction, roblox_username: str):
        if not await self.ensure_snipe_access(interaction):
            return
        if not USERNAME_RE.match(roblox_username or ""):
            return await interaction.response.send_message("Invalid Roblox username. Use 3-20 letters, numbers, or underscores.", ephemeral=True)
        wait = await self.apply_rate_limit(interaction.user)
        if wait:
            return await interaction.response.send_message(f"Cooldown active. Try again in `{wait}s`.", ephemeral=True)
        await interaction.response.defer(thinking=True)
        async with self.search_semaphore:
            result = await self.run_pipeline(roblox_username)
        await interaction.followup.send(embed=self.build_result_embed(result), view=SnipeJoinView(self, interaction.user.id, roblox_username, result))

    @snipeconfig.command(name="role", description="Set the role allowed to use Roblox Snipe.")
    async def snipeconfig_role(self, interaction: discord.Interaction, role: discord.Role):
        if not await self.ensure_config_access(interaction):
            return
        update_guild_config(interaction.guild.id, lambda config: config.update({"snipe_role": role.id}))
        await interaction.response.send_message(f"Snipe Role set to {role.mention}.", ephemeral=True)

    @snipeconfig.command(name="cooldown", description="Set Roblox Snipe cooldown seconds.")
    async def snipeconfig_cooldown(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 5, 300]):
        if not await self.ensure_config_access(interaction):
            return
        update_guild_config(interaction.guild.id, lambda config: config.update({"snipe_cooldown_seconds": int(seconds)}))
        await interaction.response.send_message(f"Snipe cooldown set to `{seconds}s`.", ephemeral=True)

    @snipeconfig.command(name="status", description="Show Roblox Snipe configuration.")
    async def snipeconfig_status(self, interaction: discord.Interaction):
        if not await self.ensure_config_access(interaction):
            return
        cfg = get_guild_config(interaction.guild.id)
        role_id = cfg.get("snipe_role")
        role = interaction.guild.get_role(role_id) if role_id else None
        embed = discord.Embed(title="Roblox Snipe Settings", color=0x5865F2)
        embed.add_field(name="Module State", value=get_module_state(cfg, "roblox_snipe"), inline=True)
        embed.add_field(name="Snipe Role", value=role.mention if role else role_id or "Not set", inline=True)
        embed.add_field(name="Cooldown", value=f"{self.cooldown_for(interaction.guild)}s", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @snipeconfig.command(name="enabled", description="Enable or disable Roblox Snipe in this server.")
    async def snipeconfig_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not await self.ensure_config_access(interaction):
            return

        def updater(config):
            set_module_state(config, "roblox_snipe", "active" if enabled else "disabled")

        update_guild_config(interaction.guild.id, updater)
        await interaction.response.send_message(f"Roblox Snipe is now `{ 'enabled' if enabled else 'disabled' }`.", ephemeral=True)
        syncer = getattr(self.bot, "sync_visible_commands", None)
        if syncer:
            await syncer(interaction.guild, reason="snipe config")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "snipe":
            return
        if not self.module_enabled(message.guild):
            return await message.channel.send("Roblox Snipe is disabled in this server.", delete_after=8)
        if not self.has_snipe_access(message.author):
            return await message.channel.send("No permission. Ask staff to configure or assign the Snipe Role.", delete_after=8)
        username = " ".join(trigger["args"]).strip()
        if not username:
            return await message.channel.send("Use `@Shorekeeper snipe RobloxUsername`.", delete_after=8)
        await self.execute_snipe(message.channel, message.author, username)


async def setup(bot):
    await bot.add_cog(RobloxSnipeCog(bot))
