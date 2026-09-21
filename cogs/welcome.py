import discord
from discord import app_commands
from discord.ext import commands

from cogs.core.responses import response_engine
from cogs.server_config import get_channel_id, get_guild_config, is_admin, update_guild_config


WELCOME_GIF = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcDFtNmx2bGwweXM4d3N2MXM5bjFvMXNpN3Q3MTQ0M2NrdmRncm55aCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/OkJat1YNdoD3W/giphy.gif"


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setupwelcome", description="Set the welcome channel.")
    async def setupwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to set the welcome channel."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        def updater(config):
            config.setdefault("channels", {})["welcome"] = channel.id

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            title="Welcome Channel Set",
            description=f"Welcome channel set to {channel.mention}."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setupgoodbye", description="Set the goodbye channel.")
    async def setupgoodbye(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to set the goodbye channel."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        def updater(config):
            config.setdefault("channels", {})["goodbye"] = channel.id

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            title="Goodbye Channel Set",
            description=f"Goodbye channel set to {channel.mention}."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setwelcomegif", description="Set the welcome GIF/image URL for this server.")
    async def setwelcomegif(self, interaction: discord.Interaction, url: str):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to set the welcome GIF."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            embed = response_engine.failure(
                title="Invalid URL",
                description="Provide a valid URL."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        def updater(config):
            config["welcome_gif_url"] = url

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            title="Welcome GIF Updated",
            description="Welcome GIF updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setgoodbyegif", description="Set the goodbye GIF/image URL for this server.")
    async def setgoodbyegif(self, interaction: discord.Interaction, url: str):
        if not is_admin(interaction.user):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to set the goodbye GIF."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            embed = response_engine.failure(
                title="Invalid URL",
                description="Provide a valid URL."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        def updater(config):
            config["goodbye_gif_url"] = url

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            title="Goodbye GIF Updated",
            description="Goodbye GIF updated."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def send_visual_message(self, member: discord.Member, channel_key: str, is_join: bool):
        channel_id = get_channel_id(member.guild.id, channel_key)
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return

        if is_join:
            text = (
                f"## Welcome {member.mention}\n"
                f"You're now part of **{member.guild.name}**.\n"
                f"Make sure to read the rules and enjoy your stay."
            )
            title = "Member Joined"
            color = 0x57F287
        else:
            text = (
                f"## Goodbye {member.mention}\n"
                f"{member.name} has left the server."
            )
            title = "Member Left"
            color = 0xED4245

        cfg = get_guild_config(member.guild.id)
        image_url = (
            cfg.get("welcome_gif_url") if is_join else cfg.get("goodbye_gif_url")
        ) or WELCOME_GIF

        embed = response_engine.build(
            title=title,
            description=text,
            color=color
        )
        embed.set_image(url=image_url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.send_visual_message(member, "welcome", is_join=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.send_visual_message(member, "goodbye", is_join=False)


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))