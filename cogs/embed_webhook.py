import discord
from discord import app_commands
from discord.ext import commands

from cogs.server_config import is_admin
from cogs.core.responses import response_engine


def parse_hex_color(value: str):
    cleaned = value.strip().lstrip("#")
    if not cleaned:
        return 0x5865F2
    return int(cleaned, 16)


class EmbedBuilderModal(discord.ui.Modal, title="Create Custom Embed"):
    title_input = discord.ui.TextInput(label="Title", max_length=256)
    description_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=4000)
    color_input = discord.ui.TextInput(label="Color (hex)", required=False, placeholder="#5865F2")
    image_input = discord.ui.TextInput(label="Image URL", required=False)
    thumbnail_input = discord.ui.TextInput(label="Thumbnail URL", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = parse_hex_color(self.color_input.value or "")
        except ValueError:
            embed = response_engine.failure(
                title="Invalid Color",
                description="The provided hex color is invalid.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.description_input.value,
            color=color,
        )
        # Add Shorekeeper footer for consistency
        embed.set_footer(text=response_engine.footer)
        if self.image_input.value:
            embed.set_image(url=self.image_input.value.strip())
        if self.thumbnail_input.value:
            embed.set_thumbnail(url=self.thumbnail_input.value.strip())
        await interaction.channel.send(embed=embed)

        success_embed = response_engine.success(
            title="Embed Sent",
            description="Your custom embed has been sent to the channel."
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


class EmbedWebhookCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Open an embed builder modal.")
    async def embed_command(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the administrative privileges to use the embed builder."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.send_modal(EmbedBuilderModal())

    @app_commands.command(name="webhook", description="Create a webhook in this channel and return URL.")
    async def webhook_command(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the administrative privileges to create webhooks."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            embed = response_engine.failure(
                title="Invalid Channel",
                description="Webhooks can only be created in text channels."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        webhook = await interaction.channel.create_webhook(name="Shorekeeper Webhook")

        success_embed = response_engine.success(
            title="Webhook Created",
            description=f"A new webhook has been established in this channel.\nURL: `{webhook.url}`"
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(EmbedWebhookCog(bot))