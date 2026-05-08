# Ticket Member Tools Cog
import discord
from discord.ext import commands


class TicketMemberTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_ticket_channel(self, channel: discord.TextChannel):
        return channel.name.startswith("ticket-")

    @commands.command(name="addtoticket")
    @commands.has_permissions(manage_channels=True)
    async def add_to_ticket(self, ctx, member: discord.Member):
        if not self.is_ticket_channel(ctx.channel):
            return await ctx.send("This is not a ticket channel.")

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
    @commands.has_permissions(manage_channels=True)
    async def remove_from_ticket(self, ctx, member: discord.Member):
        if not self.is_ticket_channel(ctx.channel):
            return await ctx.send("This is not a ticket channel.")

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
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need Manage Channels permission to use this command.")


async def setup(bot):
    await bot.add_cog(TicketMemberTools(bot))