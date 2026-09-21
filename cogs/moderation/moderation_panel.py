import discord
from discord import app_commands
from discord.ext import commands

from cogs.core.responses import response_engine
from cogs.mod_config import get_mod_guild_config, update_mod_guild_config
from cogs.module_registry import get_module_state, set_module_state
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
    "snipe": "snipe_role",
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
            embed = response_engine.failure(
                title="Panel Access Denied",
                description="This panel belongs to another user."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        if owner_only and not is_panel_owner(interaction.user.id):
            embed = response_engine.failure(
                title="Insufficient Permissions",
                description="Only the Panel Owner can use that control."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        if not owner_only and not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to use the moderation panel."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
            discord.SelectOption(label="Roblox Snipe", value="roblox_snipe", description="Snipe role, cooldown, and module state"),
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
        elif category == "roblox_snipe":
            self.add_item(ConfigButton("Set Snipe Role", "snipe_role", discord.ButtonStyle.primary))
            self.add_item(ConfigButton("Set Cooldown", "snipe_cooldown", discord.ButtonStyle.secondary))
            self.add_item(ConfigButton("Toggle Snipe", "snipe_toggle", discord.ButtonStyle.success))
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
        if self.action == "snipe_role":
            return await interaction.response.send_modal(SnipeRoleModal())
        if self.action == "snipe_cooldown":
            return await interaction.response.send_modal(SnipeCooldownModal())
        if self.action == "snipe_toggle":
            cfg = get_guild_config(interaction.guild.id)
            enabled = get_module_state(cfg, "roblox_snipe") in {"active", "debug"}

            def updater(config):
                set_module_state(config, "roblox_snipe", "disabled" if enabled else "active")

            update_guild_config(interaction.guild.id, updater)
            await interaction.response.defer()
            syncer = getattr(view.bot, "sync_visible_commands", None)
            if syncer:
                await syncer(interaction.guild, reason="snipe panel toggle")
            return await interaction.edit_original_response(embed=build_category_embed(interaction.guild, "roblox_snipe", view.bot), view=view)
        if self.action == "owner_guilds":
            ids = get_authorized_roblox_auth_guild_ids()
            lines = [f"- `{gid}` {view.bot.get_guild(gid).name if view.bot.get_guild(gid) else ''}" for gid in ids]
            embed = response_engine.info(
                title="Authorized Roblox Auth Guilds",
                description="\n".join(lines) or "No Roblox Auth guilds authorized."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: CategoryView = self.view
        if not await view.can_use(interaction):
            return
        embed = build_home_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=ModPanelView(view.bot, view.author_id))


class RoleConfigModal(discord.ui.Modal):
    role_id = discord.ui.TextInput(label="Role ID")
    role_type = discord.ui.TextInput(
        label="Type",
        placeholder="admin, mod, verify_staff, verified, ticket_ping, unverified, skip, sealed, immunity, snipe",
    )

    def __init__(self, add: bool):
        super().__init__(title="Add Role" if add else "Remove Role")
        self.add = add

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to modify roles."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Role ID",
                description="Role ID must be numeric."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
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
            embed = response_engine.failure(
                title="Invalid Role Type",
                description=str(exc)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        embed = response_engine.success(
            title="Role Setting Saved",
            description="The role setting has been successfully updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ChannelConfigModal(discord.ui.Modal, title="Set Channel"):
    channel_type = discord.ui.TextInput(
        label="Type",
        placeholder="blacklist, logging, mod_logs, track, welcome, goodbye, tickets, dashboard",
    )
    channel_id = discord.ui.TextInput(label="Channel ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to modify channels."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        key = CHANNEL_KEYS.get(self.channel_type.value.strip().lower())
        if not key:
            embed = response_engine.failure(
                title="Invalid Channel Type",
                description="The specified channel type is not recognized."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            channel_id = int(self.channel_id.value.strip())
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Channel ID",
                description="Channel ID must be numeric."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        update_guild_config(interaction.guild.id, lambda config: config.setdefault("channels", {}).update({key: channel_id}))
        embed = response_engine.success(
            title="Channel Saved",
            description="The channel setting has been successfully updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RobloxManagerRoleModal(discord.ui.Modal, title="Set Roblox Auth Manager Role"):
    role_id = discord.ui.TextInput(label="Role ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to modify the Roblox Auth manager role."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Role ID",
                description="Role ID must be numeric."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        update_mod_guild_config(interaction.guild.id, lambda config: config.update({"account_manager_role": role_id}))
        embed = response_engine.success(
            title="Roblox Auth Manager Role Saved",
            description="The Roblox Auth manager role has been successfully updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SnipeRoleModal(discord.ui.Modal, title="Set Roblox Snipe Role"):
    role_id = discord.ui.TextInput(label="Role ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to modify the Roblox Snipe role."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Role ID",
                description="Role ID must be numeric."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        update_guild_config(interaction.guild.id, lambda config: config.update({"snipe_role": role_id}))
        embed = response_engine.success(
            title="Roblox Snipe Role Saved",
            description="The Roblox Snipe role has been successfully updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SnipeCooldownModal(discord.ui.Modal, title="Set Roblox Snipe Cooldown"):
    seconds = discord.ui.TextInput(label="Cooldown Seconds", placeholder="5-300")

    async def on_submit(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to modify the Roblox Snipe cooldown."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            value = max(5, min(300, int(self.seconds.value.strip())))
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Cooldown Value",
                description="Cooldown must be a number between 5 and 300 seconds."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        update_guild_config(interaction.guild.id, lambda config: config.update({"snipe_cooldown_seconds": value}))
        embed = response_engine.success(
            title="Roblox Snipe Cooldown Saved",
            description=f"Roblox Snipe cooldown saved: `{value}s`."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def build_home_embed(guild: discord.Guild):
    cfg = get_guild_config(guild.id)
    embed = response_engine.build(
        title="Moderation Control Panel",
        description="Choose a category to view and configure existing server settings.",
        color=0xED4245  # Red color for moderation
    )
    embed.add_field(name="Admin Roles", value=str(len(cfg.get("admin_roles", []))), inline=True)
    embed.add_field(name="Mod Roles", value=str(len(cfg.get("mod_roles", []))), inline=True)
    embed.add_field(name="Immunity Role", value=_role_label(guild, cfg.get("immunity_role")), inline=True)
    return embed


def build_category_embed(guild: discord.Guild, category: str, bot):
    cfg = get_guild_config(guild.id)
    mod_cfg = get_mod_guild_config(guild.id)
    # Determine embed color based on category
    color_map = {
        "moderation": 0xED4245,  # Red
        "roles": 0x57F287,       # Green
        "channels": 0x5865F2,    # Blue
        "roblox": 0xEB459E,      # Pink/Purple
        "roblox_snipe": 0xEB459E,# Pink/Purple
        "security": 0x2B2D42,    # Dark blue
        "modules": 0xFEE75C,     # Yellow
        "owner": 0x5865F2        # Blue
    }
    color = color_map.get(category, 0x5865F2)
    embed = response_engine.build(
        title=f"{category.replace('_', ' ').title()} Settings",
        description="",
        color=color
    )
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
    elif category == "roblox_snipe":
        embed.add_field(name="Roblox Snipe", value=get_module_state(cfg, "roblox_snipe").title(), inline=True)
        embed.add_field(name="Snipe Role", value=_role_label(guild, cfg.get("snipe_role")), inline=True)
        embed.add_field(name="Cooldown", value=f"{cfg.get('snipe_cooldown_seconds', 20)} seconds", inline=True)
        embed.add_field(
            name="Authorized",
            value="Yes" if get_module_state(cfg, "roblox_snipe") in {"active", "debug"} else "No",
            inline=True
        )
        embed.add_field(
            name="Commands",
            value="`/snipe`, `/snipeconfig enabled`, `/snipeconfig role`, `/snipeconfig cooldown`, `@Shorekeeper snipe username`",
            inline=False,
        )
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
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to open the moderation panel."
            )
            return await destination.send(embed=embed)
        await destination.send(embed=build_home_embed(destination.guild), view=ModPanelView(self.bot, author.id))

    @app_commands.command(name="modpanel", description="Open the moderation configuration panel.")
    async def modpanel_slash(self, interaction: discord.Interaction):
        if not (is_panel_owner(interaction.user.id) or is_admin(interaction.user)):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to open the moderation panel."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        await interaction.response.send_message(embed=build_home_embed(interaction.guild), view=ModPanelView(self.bot, interaction.user.id), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "modpanel":
            return
        await self.send_panel(message.channel, message.author)


async def setup(bot):
    await bot.add_cog(ModerationPanel(bot))