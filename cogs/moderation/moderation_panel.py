import discord
from discord import app_commands
from discord.ext import commands

from cogs.mod_config import get_mod_guild_config, update_mod_guild_config
from cogs.server_config import (
    get_authorized_roblox_auth_guild_ids,
    get_guild_config,
    is_admin,
    is_panel_owner,
    update_guild_config,
)
from cogs.trigger_parser import parse_shorekeeper_trigger


ROLE_KEYS = {
    "admin": "admin_roles",
    "mod": "mod_roles",
    "verify_staff": "verify_staff_roles",
    "verified": "verified_roles",
    "ticket_ping": "ticket_ping_roles",
}

SINGLE_ROLE_KEYS = {
    "unverified": "unverified_role",
    "skip": "skip_role",
    "sealed": "sealed_role",
    "immunity": "immunity_role",
}

CHANNEL_KEYS = {
    "blacklist": "blacklist",
    "logging": "logging",
    "log": "logging",
    "mod_logs": "mod_logs",
    "track": "track",
    "welcome": "welcome",
    "goodbye": "goodbye",
    "tickets": "tickets",
    "dashboard": "dashboard",
}


def _role_label(guild: discord.Guild, role_id):
    role = guild.get_role(role_id) if role_id else None
    return role.mention if role else str(role_id) if role_id else "Not set"


def _channel_label(guild: discord.Guild, channel_id):
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel.mention if channel else str(channel_id) if channel_id else "Not set"


class PanelBaseView(discord.ui.View):
    def __init__(self, bot, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.author_id = author_id

    async def can_use(self, interaction: discord.Interaction, owner_only: bool = False):
        if interaction.user.id != self.author_id and not is_panel_owner(interaction.user.id):
            await interaction.response.send_message("This panel belongs to another user.", ephemeral=True)
            return False
        if owner_only and not is_panel_owner(interaction.user.id):
            await interaction.response.send_message("Only the Panel Owner can use that control.", ephemeral=True)
            return False
        if not owner_only and not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True


class ModPanelView(PanelBaseView):
    def __init__(self, bot, author_id: int):
        super().__init__(bot, author_id)
        self.add_item(CategorySelect(bot, author_id))


class CategorySelect(discord.ui.Select):
    def __init__(self, bot, author_id: int):
        self.bot = bot
        self.author_id = author_id
        options = [
            discord.SelectOption(label="Moderation", value="moderation", description="Locks, mute, blacklist, seal, purge"),
            discord.SelectOption(label="Roles", value="roles", description="Admin, mod, verified, immunity roles"),
            discord.SelectOption(label="Channels", value="channels", description="Logs, tickets, verification, dashboard channels"),
            discord.SelectOption(label="Roblox Auth", value="roblox", description="Manager role and guild authorization status"),
            discord.SelectOption(label="Security", value="security", description="Panel Owner and immunity status"),
            discord.SelectOption(label="Modules", value="modules", description="Module controls and command visibility"),
        ]
        if is_panel_owner(author_id):
            options.append(discord.SelectOption(label="Owner Panel", value="owner", description="Panel Owner-only controls"))
        super().__init__(placeholder="Choose a configuration category", options=options)

    async def callback(self, interaction: discord.Interaction):
        view = CategoryView(self.bot, self.author_id, self.values[0])
        if not await view.can_use(interaction, owner_only=self.values[0] == "owner"):
            return
        await interaction.response.edit_message(embed=build_category_embed(interaction.guild, self.values[0], self.bot), view=view)


class CategoryView(PanelBaseView):
    def __init__(self, bot, author_id: int, category: str):
        super().__init__(bot, author_id)
        self.category = category
        if category == "roles":
            self.add_item(ConfigButton("Add Role", "role_add", discord.ButtonStyle.success))
            self.add_item(ConfigButton("Remove Role", "role_remove", discord.ButtonStyle.danger))
        elif category == "channels":
            self.add_item(ConfigButton("Set Channel", "channel_set", discord.ButtonStyle.primary))
        elif category == "roblox":
            self.add_item(ConfigButton("Set Manager Role", "rbx_manager", discord.ButtonStyle.primary))
        elif category == "owner":
            self.add_item(ConfigButton("Authorized Guilds", "owner_guilds", discord.ButtonStyle.primary, owner_only=True))
        self.add_item(BackButton())


class ConfigButton(discord.ui.Button):
    def __init__(self, label: str, action: str, style: discord.ButtonStyle, owner_only: bool = False):
        super().__init__(label=label, style=style)
        self.action = action
        self.owner_only = owner_only

    async def callback(self, interaction: discord.Interaction):
        view: CategoryView = self.view
        if not await view.can_use(interaction, owner_only=self.owner_only):
            return
        if self.action == "role_add":
            return await interaction.response.send_modal(RoleConfigModal(add=True))
        if self.action == "role_remove":
            return await interaction.response.send_modal(RoleConfigModal(add=False))
        if self.action == "channel_set":
            return await interaction.response.send_modal(ChannelConfigModal())
        if self.action == "rbx_manager":
            return await interaction.response.send_modal(RobloxManagerRoleModal())
        if self.action == "owner_guilds":
            ids = get_authorized_roblox_auth_guild_ids()
            lines = [f"- `{gid}` {view.bot.get_guild(gid).name if view.bot.get_guild(gid) else ''}" for gid in ids]
            return await interaction.response.send_message("\n".join(lines) or "No Roblox Auth guilds authorized.", ephemeral=True)


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: CategoryView = self.view
        if not await view.can_use(interaction):
            return
        await interaction.response.edit_message(embed=build_home_embed(interaction.guild), view=ModPanelView(view.bot, view.author_id))


class RoleConfigModal(discord.ui.Modal):
    role_id = discord.ui.TextInput(label="Role ID")
    role_type = discord.ui.TextInput(
        label="Type",
        placeholder="admin, mod, verify_staff, verified, ticket_ping, unverified, skip, sealed, immunity",
    )

    def __init__(self, add: bool):
        super().__init__(title="Add Role" if add else "Remove Role")
        self.add = add

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("Role ID must be numeric.", ephemeral=True)
        role_type = self.role_type.value.strip().lower()

        def updater(config):
            if role_type in ROLE_KEYS:
                roles = config.setdefault(ROLE_KEYS[role_type], [])
                if self.add and role_id not in roles:
                    roles.append(role_id)
                if not self.add and role_id in roles:
                    roles.remove(role_id)
            elif role_type in SINGLE_ROLE_KEYS:
                config[SINGLE_ROLE_KEYS[role_type]] = role_id if self.add else None
            else:
                raise ValueError("Invalid role type.")

        try:
            update_guild_config(interaction.guild.id, updater)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message("Role setting saved.", ephemeral=True)


class ChannelConfigModal(discord.ui.Modal, title="Set Channel"):
    channel_type = discord.ui.TextInput(
        label="Type",
        placeholder="blacklist, logging, mod_logs, track, welcome, goodbye, tickets, dashboard",
    )
    channel_id = discord.ui.TextInput(label="Channel ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        key = CHANNEL_KEYS.get(self.channel_type.value.strip().lower())
        if not key:
            return await interaction.response.send_message("Invalid channel type.", ephemeral=True)
        try:
            channel_id = int(self.channel_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("Channel ID must be numeric.", ephemeral=True)
        update_guild_config(interaction.guild.id, lambda config: config.setdefault("channels", {}).update({key: channel_id}))
        await interaction.response.send_message("Channel saved.", ephemeral=True)


class RobloxManagerRoleModal(discord.ui.Modal, title="Set Roblox Auth Manager Role"):
    role_id = discord.ui.TextInput(label="Role ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("Role ID must be numeric.", ephemeral=True)
        update_mod_guild_config(interaction.guild.id, lambda config: config.update({"account_manager_role": role_id}))
        await interaction.response.send_message("Roblox Auth manager role saved.", ephemeral=True)


def build_home_embed(guild: discord.Guild):
    cfg = get_guild_config(guild.id)
    embed = discord.Embed(
        title="Moderation Control Panel",
        description="Choose a category to view and configure existing server settings.",
        color=discord.Color.red(),
    )
    embed.add_field(name="Admin Roles", value=str(len(cfg.get("admin_roles", []))), inline=True)
    embed.add_field(name="Mod Roles", value=str(len(cfg.get("mod_roles", []))), inline=True)
    embed.add_field(name="Immunity Role", value=_role_label(guild, cfg.get("immunity_role")), inline=True)
    return embed


def build_category_embed(guild: discord.Guild, category: str, bot):
    cfg = get_guild_config(guild.id)
    mod_cfg = get_mod_guild_config(guild.id)
    embed = discord.Embed(title=f"{category.replace('_', ' ').title()} Settings", color=0x5865F2)
    if category == "moderation":
        embed.description = "Mention commands: ban, kick, mute, warn, purge, locknick, barklock, uwulock, seal."
        embed.add_field(name="Nicklock", value="Available", inline=True)
        embed.add_field(name="Barklock / Uwulock", value="Available", inline=True)
        embed.add_field(name="Seal", value=_role_label(guild, cfg.get("sealed_role")), inline=True)
    elif category == "roles":
        embed.add_field(name="Admin Roles", value=str(len(cfg.get("admin_roles", []))), inline=True)
        embed.add_field(name="Mod Roles", value=str(len(cfg.get("mod_roles", []))), inline=True)
        embed.add_field(name="Verified Roles", value=str(len(cfg.get("verified_roles", []))), inline=True)
        embed.add_field(name="Unverified Role", value=_role_label(guild, cfg.get("unverified_role")), inline=True)
        embed.add_field(name="Immunity Role", value=_role_label(guild, cfg.get("immunity_role")), inline=True)
    elif category == "channels":
        for key in ("logging", "mod_logs", "blacklist", "track", "welcome", "goodbye", "tickets", "dashboard"):
            embed.add_field(name=key, value=_channel_label(guild, cfg.get("channels", {}).get(key)), inline=True)
    elif category == "roblox":
        embed.add_field(name="Manager Role", value=_role_label(guild, mod_cfg.get("account_manager_role")), inline=True)
        embed.add_field(name="Guild Authorized", value=str(guild.id in get_authorized_roblox_auth_guild_ids()), inline=True)
        embed.add_field(name="Owner Commands", value="`/rbxauthguild add`, `remove`, `list`", inline=False)
    elif category == "security":
        embed.add_field(name="Panel Owner", value="Configured globally", inline=True)
        embed.add_field(name="Panel Owner Immunity", value="All bot moderation actions", inline=True)
        embed.add_field(name="Immunity Role Scope", value="barklock, uwulock only", inline=False)
    elif category == "modules":
        modules = cfg.get("modules", {})
        embed.description = "\n".join(f"`{name}`: {state}" for name, state in sorted(modules.items())) or "No module overrides configured."
    elif category == "owner":
        ids = get_authorized_roblox_auth_guild_ids()
        embed.add_field(name="Authorized Roblox Auth Guilds", value=str(len(ids)), inline=True)
        embed.add_field(name="Panel Owner Controls", value="Use `/rbxauthguild` for guild authorization.", inline=False)
    return embed


class ModerationPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_panel(self, destination, author):
        if not (is_panel_owner(author.id) or is_admin(author)):
            return await destination.send("No permission.")
        await destination.send(embed=build_home_embed(destination.guild), view=ModPanelView(self.bot, author.id))

    @app_commands.command(name="modpanel", description="Open the moderation configuration panel.")
    async def modpanel_slash(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_message(embed=build_home_embed(interaction.guild), view=ModPanelView(self.bot, interaction.user.id), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "modpanel":
            return
        await self.send_panel(message.channel, message.author)


async def setup(bot):
    await bot.add_cog(ModerationPanel(bot))
