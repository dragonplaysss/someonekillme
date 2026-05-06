import discord
from discord.ext import commands

from cogs.server_config import is_panel_owner, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


ROLE_KEYS = {
    "admin": "admin_roles",
    "mod": "mod_roles",
    "verify_staff": "verify_staff_roles",
    "verified": "verified_roles",
}

SINGLE_ROLE_KEYS = {
    "unverified": "unverified_role",
    "skip": "skip_role",
    "sealed": "sealed_role",
}

CHANNEL_KEYS = {
    "blacklist": "blacklist",
    "logging": "logging",
    "log": "logging",
    "music": "music",
    "track": "track",
}


class ModPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Role", style=discord.ButtonStyle.success)
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_panel_owner(interaction.user.id):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_modal(AddRoleModal())

    @discord.ui.button(label="Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_panel_owner(interaction.user.id):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_modal(RemoveRoleModal())

    @discord.ui.button(label="Set Channels", style=discord.ButtonStyle.blurple)
    async def set_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_panel_owner(interaction.user.id):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_modal(ChannelConfigModal())


class AddRoleModal(discord.ui.Modal, title="Add Role"):
    role_id = discord.ui.TextInput(label="Role ID")
    role_type = discord.ui.TextInput(
        label="Type",
        placeholder="admin, mod, verify_staff, verified, unverified, skip, sealed",
    )

    async def on_submit(self, interaction: discord.Interaction):
        role_id = int(self.role_id.value.strip())
        role_type = self.role_type.value.strip().lower()

        def updater(config):
            if role_type in ROLE_KEYS:
                roles = config.setdefault(ROLE_KEYS[role_type], [])
                if role_id not in roles:
                    roles.append(role_id)
            elif role_type in SINGLE_ROLE_KEYS:
                config[SINGLE_ROLE_KEYS[role_type]] = role_id
            else:
                raise ValueError("Invalid role type.")

        try:
            update_guild_config(interaction.guild.id, updater)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        await interaction.response.send_message("Role saved.", ephemeral=True)


class RemoveRoleModal(discord.ui.Modal, title="Remove Role"):
    role_id = discord.ui.TextInput(label="Role ID")
    role_type = discord.ui.TextInput(
        label="Type",
        placeholder="admin, mod, verify_staff, verified, unverified, skip, sealed",
    )

    async def on_submit(self, interaction: discord.Interaction):
        role_id = int(self.role_id.value.strip())
        role_type = self.role_type.value.strip().lower()

        def updater(config):
            if role_type in ROLE_KEYS:
                roles = config.setdefault(ROLE_KEYS[role_type], [])
                if role_id in roles:
                    roles.remove(role_id)
            elif role_type in SINGLE_ROLE_KEYS:
                if config.get(SINGLE_ROLE_KEYS[role_type]) == role_id:
                    config[SINGLE_ROLE_KEYS[role_type]] = None
            else:
                raise ValueError("Invalid role type.")

        try:
            update_guild_config(interaction.guild.id, updater)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        await interaction.response.send_message("Role removed.", ephemeral=True)


class ChannelConfigModal(discord.ui.Modal, title="Set Channels"):
    channel_type = discord.ui.TextInput(
        label="Type",
        placeholder="blacklist, logging, music, track",
    )
    channel_id = discord.ui.TextInput(label="Channel ID")

    async def on_submit(self, interaction: discord.Interaction):
        channel_type = self.channel_type.value.strip().lower()
        channel_id = int(self.channel_id.value.strip())
        key = CHANNEL_KEYS.get(channel_type)

        if not key:
            return await interaction.response.send_message("Invalid channel type.", ephemeral=True)

        def updater(config):
            config.setdefault("channels", {})[key] = channel_id

        update_guild_config(interaction.guild.id, updater)
        await interaction.response.send_message("Channel saved.", ephemeral=True)


class ModerationPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_panel(self, destination, author):
        if not is_panel_owner(author.id):
            return await destination.send("No permission.")

        embed = discord.Embed(
            title="Moderation Control Panel",
            description="Manage JSON-backed server roles and channels.",
            color=discord.Color.red(),
        )

        await destination.send(embed=embed, view=ModPanelView())

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "modpanel":
            return

        await self.send_panel(message.channel, message.author)


async def setup(bot):
    await bot.add_cog(ModerationPanel(bot))
