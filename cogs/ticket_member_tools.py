# Ticket Member Tools Cog
import discord
from discord.ext import commands

from cogs.server_config import is_mod, is_owner_id


class TicketMemberTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_ticket_channel(self, channel: discord.TextChannel):
        if not isinstance(channel, discord.TextChannel):
            return False
        return bool(channel.topic and "ticket_owner=" in channel.topic)

    def can_manage_ticket(self, ctx):
        return is_mod(ctx.author) or is_owner_id(ctx.guild.id, ctx.author.id)

    def ticket_owner_id(self, channel):
        if not channel.topic:
            return None
        for part in channel.topic.split():
            if not part.startswith("ticket_owner="):
                continue
            try:
                return int(part.split("=", 1)[1])
            except Exception:
                return None
        return None

    @commands.command(name="addtoticket")
    async def add_to_ticket(self, ctx, member: discord.Member):
        if not self.is_ticket_channel(ctx.channel):
            return await ctx.send("This is not a ticket channel.")
        if not self.can_manage_ticket(ctx):
            return await ctx.send("Only ticket staff can add users.")
        if member.bot:
            return await ctx.send("Cannot add bots to tickets.")

        await ctx.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )

        embed = discord.Embed(
            title="User Added",
            description=f"{member.mention} has been added to the ticket.",
            color=0x2ECC71,
        )

        await ctx.send(embed=embed)

    @commands.command(name="removefromticket")
    async def remove_from_ticket(self, ctx, member: discord.Member):
        if not self.is_ticket_channel(ctx.channel):
            return await ctx.send("This is not a ticket channel.")
        if not self.can_manage_ticket(ctx):
            return await ctx.send("Only ticket staff can remove users.")
        if self.ticket_owner_id(ctx.channel) == member.id:
            return await ctx.send("You cannot remove the ticket owner.")

        await ctx.channel.set_permissions(member, overwrite=None)

        embed = discord.Embed(
            title="User Removed",
            description=f"{member.mention} has been removed from the ticket.",
            color=0xE74C3C,
        )

        await ctx.send(embed=embed)

    @add_to_ticket.error
    @remove_from_ticket.error
    async def ticket_permission_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send("Mention a valid member.")


async def setup(bot):
    await bot.add_cog(TicketMemberTools(bot))
