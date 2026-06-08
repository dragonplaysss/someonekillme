import json
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.server_config import is_panel_owner
from cogs.trigger_parser import parse_shorekeeper_trigger


DATA_PATH = "cogs/division_data.json"

DEFAULT_GUILD_DATA = {
    "enabled": False,
    "enabled_at": 0,
    "mainer_role": None,
    "registry_channel_id": None,
    "registry_webhook_id": None,
    "registry_webhook_token": None,
    "registry_message_id": None,
    "registry_message_ids": [],
    "division_request_channel_id": None,
    "division_requests": {},
    "divisions": {},
}

DIVIDER = "━━━━━━━━━━━━━━━━━━"
REGISTRY_WEBHOOK_NAME = "Weirwood Archive"
REGISTRY_WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/attachments/1504171315995607231/1504440222283464735/k6m64ww.avif?ex=6a06fea4&is=6a05ad24&hm=56c90191d932b4f63f632528a00919e35c1aa0a5539a606da30c87e4f10801bd&"
MAX_MEMBERS_PER_DIVISION = 30
DEFAULT_BANNER_URL = "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&"

DIVISION_THEMES = [
    {
        "match": "stark",
        "symbol": "🐺",
        "lore": '"The North remembers."',
        "color": 0x3F5361,
        "realm": "Sovereign of the North",
        "crest_url": "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&",
        "footer": "The North remembers.",
    },
    {
        "match": "targaryen",
        "symbol": "🐉",
        "lore": '"Fire and Blood."',
        "color": 0x5F0E13,
        "realm": "Blood of Old Valyria",
        "crest_url": "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&",
        "footer": "Fire and Blood.",
    },
    {
        "match": "arryn",
        "symbol": "🦅",
        "lore": '"As High as Honor."',
        "color": 0x243E73,
        "realm": "Warden of the Vale",
        "crest_url": "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&",
        "footer": "As High as Honor.",
    },
    {
        "match": "gamblers",
        "symbol": "♠️",
        "lore": '"Fortune favors the ruthless."',
        "color": 0x3A123F,
        "realm": "Covenant of the Black Table",
        "crest_url": "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&",
        "footer": "Fortune favors the ruthless.",
    },
]

FALLBACK_THEME = {
    "symbol": "⚔️",
    "lore": '"No legend has yet been written."',
    "color": 0x111827,
    "realm": "Uncharted Dominion",
    "crest_url": "https://media.discordapp.net/attachments/983632221355278387/1504443241200877700/x40b4th.png?ex=6a070173&is=6a05aff3&hm=b17335c78c22f9b6705ac9999076954940d17c571f49425dd260ee3f6478c98c&",
    "footer": "Recorded within the Weirwood Archive.",
}


def load_data():
    if not os.path.exists(DATA_PATH):
        save_data({})
        return {}

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_data(data):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_guild_data(data, guild_id):
    guild_key = str(guild_id)
    guild_data = data.setdefault(guild_key, json.loads(json.dumps(DEFAULT_GUILD_DATA)))

    for key, value in DEFAULT_GUILD_DATA.items():
        if key not in guild_data:
            guild_data[key] = json.loads(json.dumps(value))

    if not isinstance(guild_data.get("divisions"), dict):
        guild_data["divisions"] = {}

    if not isinstance(guild_data.get("registry_message_ids"), list):
        old_message_id = guild_data.get("registry_message_id")
        guild_data["registry_message_ids"] = [old_message_id] if old_message_id else []

    if not isinstance(guild_data.get("division_requests"), dict):
        guild_data["division_requests"] = {}

    return guild_data


class DivisionRequestView(discord.ui.View):
    def __init__(self, disabled=False):
        super().__init__(timeout=None)
        if disabled:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="shorekeeper_division_request_approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Divisions")
        if not cog:
            return await interaction.response.send_message("Division system is not loaded.", ephemeral=True)
        await cog.handle_request_decision(interaction, "approved")

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="shorekeeper_division_request_reject",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Divisions")
        if not cog:
            return await interaction.response.send_message("Division system is not loaded.", ephemeral=True)
        await cog.handle_request_decision(interaction, "rejected")


class Divisions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def make_embed(self, title, description, color=0x2B6CB0):
        return discord.Embed(title=title, description=description, color=color)

    async def send_embed(self, destination, title, description, color=0x2B6CB0):
        embed = self.make_embed(title, description, color)
        await destination.send(embed=embed)

    def get_division_role_ids(self, guild_data):
        role_ids = []
        for division in guild_data.get("divisions", {}).values():
            role_id = division.get("role_id")
            if role_id:
                role_ids.append(role_id)
        return role_ids

    def get_existing_division_roles(self, guild, guild_data):
        roles = []
        for role_id in self.get_division_role_ids(guild_data):
            role = guild.get_role(role_id)
            if role:
                roles.append(role)
        return roles

    def member_has_role_id(self, member, role_id):
        return any(role.id == role_id for role in member.roles)

    def member_has_division_role(self, member, division_roles):
        division_role_ids = {role.id for role in division_roles}
        return any(role.id in division_role_ids for role in member.roles)

    def get_webhook_session(self):
        return getattr(self.bot.http, "_HTTPClient__session", None)

    def get_stored_registry_webhook(self, guild_data):
        webhook_id = guild_data.get("registry_webhook_id")
        webhook_token = guild_data.get("registry_webhook_token")
        session = self.get_webhook_session()
        if not webhook_id or not webhook_token or not session:
            return None

        return discord.Webhook.partial(
            id=int(webhook_id),
            token=str(webhook_token),
            session=session,
        )

    async def get_registry_webhook_avatar(self):
        session = self.get_webhook_session()
        if not session:
            return None

        try:
            async with session.get(REGISTRY_WEBHOOK_AVATAR_URL) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except Exception:
            return None

    async def apply_registry_webhook_identity(self, webhook, guild_data):
        if guild_data.get("registry_webhook_name") == REGISTRY_WEBHOOK_NAME:
            return webhook

        avatar = await self.get_registry_webhook_avatar()
        try:
            edit_kwargs = {
                "name": REGISTRY_WEBHOOK_NAME,
                "reason": "Division registry webhook identity",
            }
            if avatar:
                edit_kwargs["avatar"] = avatar
            webhook = await webhook.edit(**edit_kwargs)
            guild_data["registry_webhook_name"] = REGISTRY_WEBHOOK_NAME
        except (discord.Forbidden, discord.HTTPException):
            pass

        return webhook

    async def create_registry_webhook(self, channel, guild_data):
        avatar = await self.get_registry_webhook_avatar()
        webhook_kwargs = {
            "name": REGISTRY_WEBHOOK_NAME,
            "reason": "Division registry panel",
        }
        if avatar:
            webhook_kwargs["avatar"] = avatar
        webhook = await channel.create_webhook(**webhook_kwargs)
        guild_data["registry_channel_id"] = channel.id
        guild_data["registry_webhook_id"] = webhook.id
        guild_data["registry_webhook_token"] = webhook.token
        guild_data["registry_webhook_name"] = REGISTRY_WEBHOOK_NAME
        return webhook

    def get_division_theme(self, name):
        lowered = name.lower()
        for theme in DIVISION_THEMES:
            if theme["match"] in lowered:
                return theme
        return FALLBACK_THEME

    def get_member_prefix(self, name):
        lowered = name.lower()
        if "stark" in lowered:
            return "Stark"
        if "arryn" in lowered:
            return "Arryn"
        if "targaryen" in lowered:
            return "Targaryen"
        if "gamblers" in lowered or "gambler" in lowered:
            return "Gambler"

        words = [word for word in name.replace("-", " ").replace("_", " ").split() if word]
        return words[-1].strip(".,:;!?") if words else "Division"

    def format_registry_title(self, name, theme):
        return f"━━━〔 {theme['symbol']} {name.upper()} 〕━━━"

    def build_registry_embeds(self, guild, guild_data):
        divisions = guild_data.get("divisions", {})
        embeds = []

        for division_id, division in sorted(divisions.items(), key=lambda item: item[1].get("name", item[0]).lower()):
            name = division.get("name", division_id)
            role = guild.get_role(division.get("role_id"))
            theme = self.get_division_theme(name)

            members = []
            if role:
                members = sorted(
                    [member for member in role.members if not member.bot],
                    key=lambda member: member.display_name.lower(),
                )

            member_prefix = self.get_member_prefix(name)
            shown_members = members[:MAX_MEMBERS_PER_DIVISION]
            member_lines = [f"╰ {member_prefix}{member.mention}" for member in shown_members]
            if len(members) > MAX_MEMBERS_PER_DIVISION:
                member_lines.append(f"╰ {len(members) - MAX_MEMBERS_PER_DIVISION} names sealed beneath the archive")
            members_text = "\n".join(member_lines) if member_lines else "╰ No sworn names recorded"

            leader = division.get("leader_id")
            leader_member = guild.get_member(leader) if leader else None
            leader_text = leader_member.mention if leader_member else "Unclaimed"
            role_text = role.mention if role else "Missing role"
            banner_url = division.get("banner_url") or DEFAULT_BANNER_URL
            crest_url = division.get("crest_url") or division.get("icon_url") or theme["crest_url"]
            lore = theme["lore"].strip(chr(34))
            population = len(members)
            population_text = f"{population:02d}" if population < 100 else str(population)

            description = (
                f"╔════════════════════════════╗\n"
                f"        {name.upper()}\n"
                f"╚════════════════════════════╝\n\n"
                f"⟡ {theme['realm'].upper()} ⟡\n"
                f"_{lore}_\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"╭─ ✦ Sovereign\n"
                f"╰ {leader_text}\n\n"
                f"╭─ ✦ House Sigil\n"
                f"╰ {role_text}\n\n"
                f"╭─ ✦ Sworn Legion\n"
                f"{members_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚔  𝑫𝑶𝑴𝑰𝑵𝑰𝑶𝑵 𝑷𝑶𝑷𝑼𝑳𝑨𝑻𝑰𝑶𝑵  •  {population_text}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

            embed = discord.Embed(
                title=self.format_registry_title(name, theme),
                description=description,
                color=theme["color"],
                timestamp=discord.utils.utcnow(),
            )
            embed.set_thumbnail(url=crest_url)
            embed.set_image(url=banner_url)
            embed.set_footer(text=f"{theme['footer']} • Shorekeeper Division Archive")
            embeds.append(embed)

        if embeds:
            return embeds

        embed = discord.Embed(
            title="━━━〔 ⚔️ NO HOUSE RECORDED 〕━━━",
            description=(
                "╔════════════════════════════╗\n"
                "        WEIRWOOD ARCHIVE\n"
                "╚════════════════════════════╝\n\n"
                "⟡ UNCHARTED DOMINION ⟡\n"
                "_No legend has yet been written._\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "╭─ ✦ Registry Status\n"
                "╰ Awaiting the first sworn division\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=FALLBACK_THEME["color"],
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=FALLBACK_THEME["crest_url"])
        embed.set_image(url=DEFAULT_BANNER_URL)
        embed.set_footer(text="Recorded within the Weirwood Archive • Shorekeeper Division Archive")
        return [embed]

    def build_registry_embed(self, guild, guild_data):
        return self.build_registry_embeds(guild, guild_data)[0]

    def build_division_request_embed(self, guild, guild_data, request):
        division_id = request["division_id"]
        division = guild_data.get("divisions", {}).get(division_id, {})
        name = division.get("name", division_id)
        theme = self.get_division_theme(name)
        applicant = guild.get_member(request["applicant_id"])
        leader = guild.get_member(division.get("leader_id")) if division.get("leader_id") else None
        role = guild.get_role(division.get("role_id")) if division.get("role_id") else None

        applicant_text = applicant.mention if applicant else f"<@{request['applicant_id']}>"
        leader_text = leader.mention if leader else "Awaiting sovereign"
        role_text = role.mention if role else "Missing role"
        status = request.get("status", "pending")
        decided_by = guild.get_member(request.get("decided_by")) if request.get("decided_by") else None
        decided_by_text = decided_by.mention if decided_by else "Unknown"
        joined_at = request.get("joined_at", 0)
        created_at = request.get("created_at", 0)
        requested_at = request.get("requested_at", 0)

        if status == "approved":
            judgment = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚔  𝑺𝑾𝑶𝑹𝑵 𝑰𝑵𝑻𝑶 {name.upper()}  ⚔\n"
                f"╭─ ✦ Approved By\n"
                f"╰ {decided_by_text}"
            )
            color = 0x2F5D46
        elif status == "rejected":
            judgment = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✦  𝑹𝑬𝑸𝑼𝑬𝑺𝑻 𝑹𝑬𝑱𝑬𝑪𝑻𝑬𝑫\n"
                f"╭─ ✦ Judged By\n"
                f"╰ {decided_by_text}"
            )
            color = 0x5F0E13
        else:
            judgment = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚔ Awaiting judgment from the Sovereign."
            )
            color = theme["color"]

        description = (
            f"╔════════════════════════════╗\n"
            f"        {name.upper()} REQUEST\n"
            f"╚════════════════════════════╝\n\n"
            f"⟡ {theme['realm'].upper()} ⟡\n"
            f"_{theme['lore'].strip(chr(34))}_\n\n"
            f"╭─ ✦ Applicant\n"
            f"╰ {applicant_text}\n\n"
            f"╭─ ✦ Requested House\n"
            f"╰ {name}\n\n"
            f"╭─ ✦ House Sigil\n"
            f"╰ {role_text}\n\n"
            f"╭─ ✦ Rank / Stage\n"
            f"╰ {request.get('rank_stage') or 'Unrecorded'}\n\n"
            f"╭─ ✦ Joined Server\n"
            f"╰ <t:{joined_at}:R>\n\n"
            f"╭─ ✦ Account Created\n"
            f"╰ <t:{created_at}:R>\n\n"
            f"╭─ ✦ Sovereign\n"
            f"╰ {leader_text}\n\n"
            f"╭─ ✦ Petition Filed\n"
            f"╰ <t:{requested_at}:R>\n\n"
            f"{judgment}"
        )

        embed = discord.Embed(
            title=f"━━━〔 {theme['symbol']} {name.upper()} REQUEST 〕━━━",
            description=description,
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=division.get("crest_url") or theme["crest_url"])
        embed.set_image(url=division.get("banner_url") or DEFAULT_BANNER_URL)
        embed.set_footer(text=f"{theme['footer']} • Shorekeeper Division Archive")
        return embed

    def get_pending_request_for_member(self, guild_data, member_id):
        for request in guild_data.get("division_requests", {}).values():
            if request.get("applicant_id") == member_id and request.get("status") == "pending":
                return request
        return None

    def can_manage_division_request(self, member, division):
        if is_panel_owner(member.id):
            return True
        return division.get("leader_id") == member.id

    async def handle_request_decision(self, interaction, decision):
        if not interaction.guild or not interaction.message:
            return await interaction.response.send_message("This request is no longer available.", ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        requests = guild_data.setdefault("division_requests", {})
        request = requests.get(str(interaction.message.id))
        if not request:
            return await interaction.response.send_message("This request is no longer tracked.", ephemeral=True)

        if request.get("status") != "pending":
            embed = self.build_division_request_embed(interaction.guild, guild_data, request)
            return await interaction.response.edit_message(embed=embed, view=DivisionRequestView(disabled=True))

        division = guild_data.get("divisions", {}).get(request["division_id"])
        if not division:
            return await interaction.response.send_message("The requested division no longer exists.", ephemeral=True)

        if not self.can_manage_division_request(interaction.user, division):
            return await interaction.response.send_message(
                "Only panel owners or this division's leader can judge this request.",
                ephemeral=True,
            )

        if decision == "approved":
            applicant = interaction.guild.get_member(request["applicant_id"])
            role = interaction.guild.get_role(division.get("role_id"))
            if not applicant:
                return await interaction.response.send_message("Applicant is no longer in this server.", ephemeral=True)
            if not role:
                return await interaction.response.send_message("The division role no longer exists.", ephemeral=True)

            try:
                previous_roles = self.get_existing_division_roles(interaction.guild, guild_data)
                roles_to_remove = [old_role for old_role in previous_roles if old_role in applicant.roles]
                if roles_to_remove:
                    await applicant.remove_roles(*roles_to_remove, reason="Division request approved")
                await applicant.add_roles(role, reason="Division request approved")
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "I could not update roles. Put my role higher than division roles.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return await interaction.response.send_message(
                    "Discord rejected the role update. Try again in a moment.",
                    ephemeral=True,
                )

        request["status"] = decision
        request["decided_by"] = interaction.user.id
        request["decided_at"] = int(time.time())
        save_data(data)

        if decision == "approved":
            await self.update_registry_message(interaction.guild)

        embed = self.build_division_request_embed(interaction.guild, guild_data, request)
        await interaction.response.edit_message(embed=embed, view=DivisionRequestView(disabled=True))

    def get_registry_message_ids(self, guild_data):
        message_ids = guild_data.get("registry_message_ids")
        if isinstance(message_ids, list):
            return [int(message_id) for message_id in message_ids if message_id]

        message_id = guild_data.get("registry_message_id")
        return [int(message_id)] if message_id else []

    def chunk_registry_embeds(self, embeds):
        return [embeds[index:index + 10] for index in range(0, len(embeds), 10)]

    async def reset_registry_embeds(self, webhook, guild_data, embeds):
        for message_id in self.get_registry_message_ids(guild_data):
            try:
                await webhook.delete_message(message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        new_message_ids = []
        for embed_chunk in self.chunk_registry_embeds(embeds):
            message = await webhook.send(embeds=embed_chunk, wait=True)
            new_message_ids.append(message.id)

        guild_data["registry_message_ids"] = new_message_ids
        guild_data["registry_message_id"] = new_message_ids[0] if new_message_ids else None

    async def edit_registry_embeds(self, webhook, guild_data, embeds):
        message_ids = self.get_registry_message_ids(guild_data)
        embed_chunks = self.chunk_registry_embeds(embeds)

        if len(message_ids) != len(embed_chunks):
            await self.reset_registry_embeds(webhook, guild_data, embeds)
            return

        for message_id, embed_chunk in zip(message_ids, embed_chunks):
            await webhook.edit_message(message_id, embeds=embed_chunk)

    async def update_registry_message(self, guild):
        data = load_data()
        guild_data = get_guild_data(data, guild.id)
        channel_id = guild_data.get("registry_channel_id")
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embeds = self.build_registry_embeds(guild, guild_data)
        webhook = None
        try:
            webhook = self.get_stored_registry_webhook(guild_data)
            if not webhook:
                webhook = await self.create_registry_webhook(channel, guild_data)
            else:
                webhook = await self.apply_registry_webhook_identity(webhook, guild_data)

            await self.edit_registry_embeds(webhook, guild_data, embeds)
            save_data(data)
        except discord.NotFound:
            try:
                if webhook:
                    await self.reset_registry_embeds(webhook, guild_data, embeds)
                else:
                    webhook = await self.create_registry_webhook(channel, guild_data)
                    await self.reset_registry_embeds(webhook, guild_data, embeds)
            except discord.NotFound:
                webhook = await self.create_registry_webhook(channel, guild_data)
                await self.reset_registry_embeds(webhook, guild_data, embeds)
            except (discord.Forbidden, discord.HTTPException):
                return
            save_data(data)
        except (discord.Forbidden, discord.HTTPException):
            return

    async def require_panel_owner(self, interaction):
        if is_panel_owner(interaction.user.id):
            return True

        embed = self.make_embed(
            "No Permission",
            "Only panel owners can use this command.",
            0xED4245,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    @app_commands.command(name="setupdivisions", description="Create or update a division.")
    async def setupdivisions(
        self,
        interaction: discord.Interaction,
        unique_id: str,
        name: str,
        role: discord.Role,
    ):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        unique_id = unique_id.strip()
        name = name.strip()

        if not unique_id or unique_id != unique_id.lower():
            embed = self.make_embed(
                "Invalid Division ID",
                "Division IDs must be lowercase.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not name:
            embed = self.make_embed("Invalid Name", "Division name cannot be empty.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        existed = unique_id in guild_data["divisions"]
        existing_division = guild_data["divisions"].get(unique_id, {})
        guild_data["divisions"][unique_id] = {
            "name": name,
            "role_id": role.id,
            "leader_id": existing_division.get("leader_id"),
            "banner_url": existing_division.get("banner_url"),
            "crest_url": existing_division.get("crest_url"),
        }
        save_data(data)
        await self.update_registry_message(interaction.guild)

        action = "updated" if existed else "created"
        embed = self.make_embed(
            "Division Saved",
            f"`{unique_id}` {action} as **{name}** using {role.mention}.",
            0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="removedivision", description="Remove a configured division.")
    async def removedivision(self, interaction: discord.Interaction, division_id: str):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        division_id = division_id.strip().lower()

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        divisions = guild_data["divisions"]
        division = divisions.get(division_id)
        if not division:
            embed = self.make_embed(
                "Unknown Division",
                f"`{division_id}` is not a configured division.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        division_name = division.get("name", division_id)
        del divisions[division_id]

        division_requests = guild_data.setdefault("division_requests", {})
        for request_id, request in list(division_requests.items()):
            if request.get("division_id") == division_id and request.get("status") == "pending":
                del division_requests[request_id]

        save_data(data)
        await self.update_registry_message(interaction.guild)

        embed = self.make_embed(
            "Division Removed",
            f"**{division_name}** (`{division_id}`) was removed.",
            0x57F287,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setupdivisionregistry", description="Post or move the persistent division registry panel.")
    async def setupdivisionregistry(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            embed = self.make_embed("Invalid Channel", "Choose a text channel for the registry.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        embeds = self.build_registry_embeds(interaction.guild, guild_data)

        try:
            same_channel = guild_data.get("registry_channel_id") == target_channel.id
            webhook = self.get_stored_registry_webhook(guild_data) if same_channel else None
            if not same_channel:
                old_webhook = self.get_stored_registry_webhook(guild_data)
                if old_webhook:
                    for message_id in self.get_registry_message_ids(guild_data):
                        try:
                            await old_webhook.delete_message(message_id)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            continue
                guild_data["registry_message_ids"] = []
                guild_data["registry_message_id"] = None

            if not webhook:
                webhook = await self.create_registry_webhook(target_channel, guild_data)
            else:
                webhook = await self.apply_registry_webhook_identity(webhook, guild_data)

            if same_channel and self.get_registry_message_ids(guild_data):
                try:
                    await self.edit_registry_embeds(webhook, guild_data, embeds)
                except discord.NotFound:
                    try:
                        await self.reset_registry_embeds(webhook, guild_data, embeds)
                    except discord.NotFound:
                        webhook = await self.create_registry_webhook(target_channel, guild_data)
                        await self.reset_registry_embeds(webhook, guild_data, embeds)
            else:
                try:
                    await self.reset_registry_embeds(webhook, guild_data, embeds)
                except discord.NotFound:
                    webhook = await self.create_registry_webhook(target_channel, guild_data)
                    await self.reset_registry_embeds(webhook, guild_data, embeds)
        except discord.Forbidden:
            error_embed = self.make_embed(
                "Webhook Permission Missing",
                "I need permission to manage webhooks in that channel.",
                0xED4245,
            )
            return await interaction.followup.send(embed=error_embed, ephemeral=True)
        except discord.HTTPException:
            error_embed = self.make_embed(
                "Webhook Update Failed",
                "Discord rejected the registry webhook update. Try again in a moment.",
                0xED4245,
            )
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        guild_data["registry_channel_id"] = target_channel.id
        guild_data["registry_webhook_id"] = webhook.id
        guild_data["registry_webhook_token"] = webhook.token
        save_data(data)

        response_embed = self.make_embed(
            "Division Registry Linked",
            f"The webhook registry panel is now bound to {target_channel.mention}.",
            0x57F287,
        )
        await interaction.followup.send(embed=response_embed, ephemeral=True)

    @app_commands.command(name="setdivisionrequestchannel", description="Set the channel for division applications.")
    async def setdivisionrequestchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        guild_data["division_request_channel_id"] = channel.id
        save_data(data)

        embed = self.make_embed(
            "Division Request Channel Set",
            f"Division applications will now be sent to {channel.mention}.",
            0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="diviupdatewbh", description="Update the leader shown on the division registry webhook.")
    async def diviupdatewbh(
        self,
        interaction: discord.Interaction,
        division_id: str,
        leader: discord.Member,
    ):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        division_id = division_id.strip().lower()
        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        division = guild_data.get("divisions", {}).get(division_id)
        if not division:
            embed = self.make_embed(
                "Unknown Division",
                f"`{division_id}` is not a configured division.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        division["leader_id"] = leader.id
        save_data(data)
        await self.update_registry_message(interaction.guild)

        embed = self.make_embed(
            "Division Leader Updated",
            f"**{division.get('name', division_id)}** is now led by {leader.mention}.",
            0x57F287,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setdivisionbanner", description="Set the banner image shown on a division registry embed.")
    async def setdivisionbanner(
        self,
        interaction: discord.Interaction,
        division_id: str,
        banner_url: str,
    ):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        division_id = division_id.strip().lower()
        banner_url = banner_url.strip()
        if not banner_url.startswith(("http://", "https://")):
            embed = self.make_embed(
                "Invalid Banner URL",
                "Banner URL must start with `http://` or `https://`.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        division = guild_data.get("divisions", {}).get(division_id)
        if not division:
            embed = self.make_embed(
                "Unknown Division",
                f"`{division_id}` is not a configured division.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        division["banner_url"] = banner_url
        save_data(data)
        await self.update_registry_message(interaction.guild)

        embed = self.make_embed(
            "Division Banner Updated",
            f"**{division.get('name', division_id)}** now has a registry banner.",
            0x57F287,
        )
        embed.set_image(url=banner_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setdivisioncrest", description="Set the crest thumbnail shown on a division registry embed.")
    async def setdivisioncrest(
        self,
        interaction: discord.Interaction,
        division_id: str,
        crest_url: str,
    ):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        division_id = division_id.strip().lower()
        crest_url = crest_url.strip()
        if not crest_url.startswith(("http://", "https://")):
            embed = self.make_embed(
                "Invalid Crest URL",
                "Crest URL must start with `http://` or `https://`.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        division = guild_data.get("divisions", {}).get(division_id)
        if not division:
            embed = self.make_embed(
                "Unknown Division",
                f"`{division_id}` is not a configured division.",
                0xED4245,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        division["crest_url"] = crest_url
        save_data(data)
        await self.update_registry_message(interaction.guild)

        embed = self.make_embed(
            "Division Crest Updated",
            f"**{division.get('name', division_id)}** now has a registry crest.",
            0x57F287,
        )
        embed.set_thumbnail(url=crest_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setmainerrole", description="Set the role required to join divisions.")
    async def setmainerrole(self, interaction: discord.Interaction, role: discord.Role):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        guild_data["mainer_role"] = role.id
        save_data(data)

        embed = self.make_embed(
            "Mainer Role Set",
            f"Only members with {role.mention} can join divisions.",
            0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="enablejoindivisions", description="Enable division joining.")
    async def enablejoindivisions(self, interaction: discord.Interaction):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        enabled_at = int(time.time())
        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        guild_data["enabled"] = True
        guild_data["enabled_at"] = enabled_at
        save_data(data)

        embed = self.make_embed(
            "Division Joining Enabled",
            f"Members who join after <t:{enabled_at}:F> can be equalized into divisions.",
            0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="disablejoindivisions", description="Disable division joining.")
    async def disablejoindivisions(self, interaction: discord.Interaction):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)
        guild_data["enabled"] = False
        save_data(data)

        embed = self.make_embed(
            "Division Joining Disabled",
            "Members can no longer join divisions.",
            0xED4245,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="equalizedivisions", description="Auto assign eligible new members to divisions.")
    async def equalizedivisions(self, interaction: discord.Interaction):
        if not await self.require_panel_owner(interaction):
            return

        if not interaction.guild:
            embed = self.make_embed("Server Only", "Use this command in a server.", 0xED4245)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        data = load_data()
        guild_data = get_guild_data(data, interaction.guild.id)

        if not guild_data.get("enabled"):
            embed = self.make_embed(
                "Division Joining Disabled",
                "Enable division joining before equalizing members.",
                0xED4245,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        mainer_role_id = guild_data.get("mainer_role")
        mainer_role = interaction.guild.get_role(mainer_role_id) if mainer_role_id else None
        if not mainer_role:
            embed = self.make_embed(
                "Missing Mainer Role",
                "Set a valid mainer role before equalizing divisions.",
                0xED4245,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        divisions = guild_data.get("divisions", {})
        if not divisions:
            embed = self.make_embed(
                "No Divisions",
                "Create at least one division before equalizing members.",
                0xED4245,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        valid_divisions = {}
        for division_id, division in divisions.items():
            role = interaction.guild.get_role(division.get("role_id"))
            if role:
                valid_divisions[division_id] = {
                    "name": division.get("name", division_id),
                    "role": role,
                }

        if not valid_divisions:
            embed = self.make_embed(
                "Missing Division Roles",
                "None of the configured division roles exist in this server.",
                0xED4245,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        division_roles = [division["role"] for division in valid_divisions.values()]
        division_counts = {
            division_id: sum(1 for member in role.members if not member.bot)
            for division_id, division in valid_divisions.items()
            for role in [division["role"]]
        }

        enabled_at = int(guild_data.get("enabled_at") or 0)
        candidates = []
        for member in interaction.guild.members:
            if member.bot:
                continue
            if not self.member_has_role_id(member, mainer_role.id):
                continue
            if not member.joined_at or int(member.joined_at.timestamp()) <= enabled_at:
                continue
            if self.member_has_division_role(member, division_roles):
                continue
            candidates.append(member)

        candidates.sort(key=lambda member: member.joined_at)

        assigned = 0
        failed = 0
        for member in candidates:
            division_id = min(
                valid_divisions,
                key=lambda current_id: (
                    division_counts[current_id],
                    valid_divisions[current_id]["name"].lower(),
                    current_id,
                ),
            )
            role = valid_divisions[division_id]["role"]

            try:
                await member.add_roles(role, reason="Division equalization")
                division_counts[division_id] += 1
                assigned += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1

        await self.update_registry_message(interaction.guild)

        summary = [f"Assigned **{assigned}** eligible member(s)."]
        if failed:
            summary.append(f"Failed to assign **{failed}** member(s). Check role hierarchy.")

        counts_text = "\n".join(
            f"`{division_id}`: {division_counts[division_id]}"
            for division_id in sorted(valid_divisions)
        )
        embed = self.make_embed(
            "Divisions Equalized",
            "\n".join(summary),
            0x57F287 if failed == 0 else 0xFEE75C,
        )
        embed.add_field(name="Current Counts", value=counts_text or "No counts available.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] not in {"joindivision", "leavedivision"}:
            return

        if trigger["keyword"] == "joindivision":
            await self.handle_join_division(message, trigger)
        else:
            await self.handle_leave_division(message)

    async def handle_join_division(self, message, trigger):
        data = load_data()
        guild_data = get_guild_data(data, message.guild.id)

        if not guild_data.get("enabled"):
            return await self.send_embed(
                message.channel,
                "Division Joining Disabled",
                "Division joining is not currently enabled.",
                0xED4245,
            )

        mainer_role_id = guild_data.get("mainer_role")
        mainer_role = message.guild.get_role(mainer_role_id) if mainer_role_id else None
        if not mainer_role:
            return await self.send_embed(
                message.channel,
                "Missing Mainer Role",
                "The required mainer role has not been configured or no longer exists.",
                0xED4245,
            )

        if not self.member_has_role_id(message.author, mainer_role.id):
            return await self.send_embed(
                message.channel,
                "Verification Required",
                f"You need {mainer_role.mention} before joining a division.",
                0xED4245,
            )

        if not trigger["args"]:
            return await self.send_embed(
                message.channel,
                "Missing Division ID",
                "Use `joindivision <division_id>;<rank_or_stage>`.",
                0xED4245,
            )

        division_id = trigger["args"][0].lower()
        rank_stage = trigger.get("extra", "").strip()
        if not rank_stage:
            return await self.send_embed(
                message.channel,
                "Missing Rank / Stage",
                "Use `joindivision <division_id>;<rank_or_stage>`.",
                0xED4245,
            )

        division = guild_data.get("divisions", {}).get(division_id)
        if not division:
            return await self.send_embed(
                message.channel,
                "Unknown Division",
                f"`{division_id}` is not a configured division.",
                0xED4245,
            )

        division_role = message.guild.get_role(division.get("role_id"))
        if not division_role:
            return await self.send_embed(
                message.channel,
                "Missing Division Role",
                f"The role for `{division_id}` no longer exists.",
                0xED4245,
            )

        if division_role in message.author.roles:
            return await self.send_embed(
                message.channel,
                "Already Sworn",
                f"You are already in **{division.get('name', division_id)}**.",
                0xED4245,
            )

        pending_request = self.get_pending_request_for_member(guild_data, message.author.id)
        if pending_request:
            return await self.send_embed(
                message.channel,
                "Request Already Pending",
                "You already have a pending division application awaiting judgment.",
                0xED4245,
            )

        request_channel_id = guild_data.get("division_request_channel_id")
        request_channel = message.guild.get_channel(request_channel_id) if request_channel_id else None
        if not isinstance(request_channel, discord.TextChannel):
            return await self.send_embed(
                message.channel,
                "Request Channel Missing",
                "A panel owner must set `/setdivisionrequestchannel` before applications can be filed.",
                0xED4245,
            )

        requested_at = int(time.time())
        request = {
            "guild_id": message.guild.id,
            "applicant_id": message.author.id,
            "division_id": division_id,
            "rank_stage": rank_stage,
            "status": "pending",
            "requested_at": requested_at,
            "joined_at": int(message.author.joined_at.timestamp()) if message.author.joined_at else requested_at,
            "created_at": int(message.author.created_at.timestamp()),
            "message_id": None,
            "channel_id": request_channel.id,
        }

        leader = message.guild.get_member(division.get("leader_id")) if division.get("leader_id") else None
        content = leader.mention if leader else None
        embed = self.build_division_request_embed(message.guild, guild_data, request)
        sent_message = await request_channel.send(
            content=content,
            embed=embed,
            view=DivisionRequestView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

        request["message_id"] = sent_message.id
        guild_data.setdefault("division_requests", {})[str(sent_message.id)] = request
        save_data(data)

        await self.send_embed(
            message.channel,
            "Division Request Filed",
            f"{message.author.mention}, your request for **{division.get('name', division_id)}** has been sent for judgment.",
            0x57F287,
        )

    async def handle_leave_division(self, message):
        data = load_data()
        guild_data = get_guild_data(data, message.guild.id)
        division_roles = self.get_existing_division_roles(message.guild, guild_data)
        roles_to_remove = [role for role in division_roles if role in message.author.roles]

        if not roles_to_remove:
            return await self.send_embed(
                message.channel,
                "No Division Role",
                "You are not currently in a division.",
                0xFEE75C,
            )

        try:
            await message.author.remove_roles(*roles_to_remove, reason="Left division")
        except discord.Forbidden:
            return await self.send_embed(
                message.channel,
                "Role Hierarchy Error",
                "I could not remove your division role. Put my role higher than division roles.",
                0xED4245,
            )
        except discord.HTTPException:
            return await self.send_embed(
                message.channel,
                "Role Update Failed",
                "Discord rejected the role update. Try again in a moment.",
                0xED4245,
            )

        await self.send_embed(
            message.channel,
            "Division Left",
            f"{message.author.mention} left their division.",
            0x57F287,
        )
        await self.update_registry_message(message.guild)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.bot or before.guild != after.guild:
            return

        data = load_data()
        guild_data = get_guild_data(data, after.guild.id)
        division_role_ids = set(self.get_division_role_ids(guild_data))
        if not division_role_ids:
            return

        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}
        if before_role_ids & division_role_ids != after_role_ids & division_role_ids:
            await self.update_registry_message(after.guild)


async def setup(bot):
    bot.add_view(DivisionRequestView())
    await bot.add_cog(Divisions(bot))
