# -*- coding: utf-8 -*-
"""Ticket system (UTF-8 source). Run scripts/fix_nullbytes.py if the file ever corrupts with NUL bytes."""

import io
import os
import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from cogs.server_config import get_channel_id, get_guild_config, is_admin, is_mod, is_owner_id
from cogs.trigger_parser import parse_shorekeeper_trigger


STAFF_ROLE_NAME = os.getenv("TICKET_STAFF_ROLE_NAME", "Staff")

TICKET_NAME_PREFIXES = ("support-", "merge-", "report-", "suggestion-", "ticket-")
TICKET_TOPIC_MARKER = "ticket_owner="


def _ticket_channel_name_pattern():
    return re.compile(r"^(support|merge|report|suggestion|ticket)-\d+$")


class TicketCloseView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.close_ticket(interaction)


class SupportTicketModal(discord.ui.Modal, title="Support Ticket"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.help_with = discord.ui.TextInput(
            label="What do you need help with?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
            placeholder="Describe your issue clearly...",
        )
        self.add_item(self.help_with)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket_from_modal(
            interaction,
            "support",
            {"What do you need help with?": self.help_with.value},
        )


class MergeTicketModal(discord.ui.Modal, title="Clan Merge / Alliance"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.clan_name = discord.ui.TextInput(
            label="Clan Name",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.member_count = discord.ui.TextInput(
            label="Member Count",
            style=discord.TextStyle.short,
            required=True,
            max_length=20,
        )
        self.why_merge = discord.ui.TextInput(
            label="Why do you want to merge/alliance?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
            placeholder="Explain your goals for a merge or alliance...",
        )
        self.add_item(self.clan_name)
        self.add_item(self.member_count)
        self.add_item(self.why_merge)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket_from_modal(
            interaction,
            "merge",
            {
                "Clan Name": self.clan_name.value,
                "Member Count": self.member_count.value,
                "Why do you want to merge/alliance?": self.why_merge.value,
            },
        )


class ReportTicketModal(discord.ui.Modal, title="Member/Staff Report"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.who = discord.ui.TextInput(
            label="Who are you reporting?",
            style=discord.TextStyle.short,
            required=True,
            max_length=200,
        )
        self.what = discord.ui.TextInput(
            label="What happened?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )
        self.add_item(self.who)
        self.add_item(self.what)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket_from_modal(
            interaction,
            "report",
            {
                "Who are you reporting?": self.who.value,
                "What happened?": self.what.value,
            },
        )


class SuggestionTicketModal(discord.ui.Modal, title="Suggestion"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.suggestion = discord.ui.TextInput(
            label="Suggestion text",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
            placeholder="Your idea for the server or clan...",
        )
        self.add_item(self.suggestion)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket_from_modal(
            interaction,
            "suggestion",
            {"Suggestion text": self.suggestion.value},
        )


class TicketPanelView(discord.ui.View):
    """Persistent panel: dropdown opens category-specific modals."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        placeholder="Choose a ticket category...",
        custom_id="shorekeeper:ticket_panel_select",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="Support Ticket",
                value="support",
                description="Get help from staff",
            ),
            discord.SelectOption(
                label="Clan Merge / Alliance",
                value="merge",
                description="Merge or alliance request",
            ),
            discord.SelectOption(
                label="Member/Staff Report",
                value="report",
                description="Report a member or staff",
            ),
            discord.SelectOption(
                label="Suggestion",
                value="suggestion",
                description="Share an idea",
            ),
        ],
    )
    async def ticket_category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        value = select.values[0]
        modals = {
            "support": SupportTicketModal,
            "merge": MergeTicketModal,
            "report": ReportTicketModal,
            "suggestion": SuggestionTicketModal,
        }
        modal_cls = modals.get(value)
        if not modal_cls:
            return await interaction.response.send_message("Invalid selection.", ephemeral=True)
        await interaction.response.send_modal(modal_cls(self.cog))


class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketCloseView(self))

    def get_staff_role(self, guild: discord.Guild):
        return discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)

    def _configured_ticket_roles(self, guild: discord.Guild):
        cfg = get_guild_config(guild.id)
        role_ids = set(cfg.get("ticket_ping_roles", []))
        role_ids.update(cfg.get("admin_roles", []))
        role_ids.update(cfg.get("mod_roles", []))
        staff_role = self.get_staff_role(guild)
        if staff_role:
            role_ids.add(staff_role.id)
        return [role for role_id in role_ids if (role := guild.get_role(role_id))]

    def _user_has_open_ticket(self, guild: discord.Guild, user_id: int):
        pattern = _ticket_channel_name_pattern()
        for ch in guild.text_channels:
            if not isinstance(ch, discord.TextChannel):
                continue
            if not ch.topic or TICKET_TOPIC_MARKER not in ch.topic:
                continue
            if self._ticket_owner_id_from_topic(ch) != user_id:
                continue
            if pattern.match(ch.name):
                return ch
        return None

    @app_commands.command(name="ticketpanel", description="Send the ticket open panel.")
    async def ticketpanel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_admin(interaction.user):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        embed = discord.Embed(
            title="Tickets",
            description=(
                "**Select a category** from the menu below.\n"
                "You will be asked a few questions, then a private channel will open.\n\n"
                "`---`\n"
                "Support  Merge / Alliance  Reports  Suggestions"
            ),
            color=0x1E1B2E,
        )
        embed.set_footer(text="Shorekeeper Ticket System")

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await interaction.followup.send(
                "Run this from a **text channel** or a **thread** the bot can post in.",
                ephemeral=True,
            )

        try:
            await channel.send(embed=embed, view=TicketPanelView(self))
        except discord.Forbidden:
            return await interaction.followup.send(
                "I cannot post here. Give the bot **Send Messages** and **Embed Links** in this channel.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                f"Discord rejected the panel message ({exc.status}): `{exc.text[:500]}`.",
                ephemeral=True,
            )
        except Exception as exc:
            return await interaction.followup.send(
                f"Could not post panel: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

        await interaction.followup.send("Ticket panel sent.", ephemeral=True)

    def _is_ticket_channel(self, channel: discord.abc.GuildChannel):
        if not isinstance(channel, discord.TextChannel):
            return False
        if channel.name.startswith(TICKET_NAME_PREFIXES) and channel.topic and TICKET_TOPIC_MARKER in channel.topic:
            return True
        return bool(channel.topic and TICKET_TOPIC_MARKER in channel.topic)

    def _ticket_owner_id_from_topic(self, channel: discord.TextChannel):
        if not channel.topic:
            return None
        prefix = "ticket_owner="
        for part in channel.topic.split():
            if part.startswith(prefix):
                try:
                    return int(part[len(prefix) :])
                except Exception:
                    return None
        return None

    def _can_manage_ticket(self, member: discord.Member, channel: discord.TextChannel, allow_owner=True):
        owner_id = self._ticket_owner_id_from_topic(channel)
        if allow_owner and owner_id is not None and member.id == owner_id:
            return True
        return is_mod(member) or is_owner_id(channel.guild.id, member.id)

    def _ticket_allowed_mentions(self, user: discord.abc.User, roles):
        return discord.AllowedMentions(
            users=[user],
            roles=roles,
            everyone=False,
            replied_user=False,
        )

    async def build_transcript_file(self, channel: discord.TextChannel):
        lines = []
        async for msg in channel.history(limit=500, oldest_first=True):
            clean = (msg.content or "").replace("\n", " ").strip()
            if msg.attachments:
                att_urls = " ".join(a.url for a in msg.attachments)
                clean = f"{clean} [attachments: {att_urls}]".strip()
            lines.append(f"[{msg.created_at.isoformat()}] {msg.author} ({msg.author.id}): {clean}")

        transcript = "\n".join(lines) if lines else "No messages in ticket."
        return discord.File(
            io.BytesIO(transcript.encode("utf-8")),
            filename=f"{channel.name}-transcript.txt",
        )

    async def send_transcript_to_logs(self, guild: discord.Guild, closed_by: discord.abc.User, channel: discord.TextChannel):
        transcript_file = await self.build_transcript_file(channel)
        log_channel_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        if not log_channel:
            return False, "No log channel configured. Set `mod_logs` or `logging`."

        try:
            await log_channel.send(
                content=f"Archived ticket `{channel.name}` by {closed_by.mention}.",
                file=transcript_file,
            )
            return True, f"Archived to {log_channel.mention}."
        except discord.Forbidden:
            return False, f"I don't have permission to post in {log_channel.mention}."
        except Exception as exc:
            return False, f"Failed to post transcript: {type(exc).__name__}: {exc}"

    def _embed_answers(self, category_key: str, answers: dict) -> discord.Embed:
        titles = {
            "support": "Ticket Opened",
            "merge": "Merge / Alliance Ticket",
            "report": "Report Ticket",
            "suggestion": "Suggestion Ticket",
        }
        labels = {
            "support": "Support",
            "merge": "Merge",
            "report": "Report",
            "suggestion": "Suggestion",
        }
        title = f"{labels.get(category_key, 'Ticket')} - {titles.get(category_key, 'Ticket')}"
        desc_lines = ["**Submitted information**", "`---`"]
        for k, v in answers.items():
            desc_lines.append(f"**{k}**")
            desc_lines.append(f"```{v[:1900]}```" if len(v) > 400 else f"> {v}")
            desc_lines.append("")
        embed = discord.Embed(
            title=title,
            description="\n".join(desc_lines).strip()[:4000],
            color=0x2B2D31,
        )
        return embed

    def _embed_rules(self, category_key: str) -> discord.Embed:
        if category_key == "merge":
            embed = discord.Embed(
                title="Merge / Alliance - Oaths before the council",
                description=(
                    "*Whether you bend the knee* **(merge)** *or swear the sword at our side* **(alliance)**, "
                    "these are the **terms of the house** - read them once, understand them fully.\n\n"
                    "`%%%%%%%%%%%%`\n"
                    "**What you are asking for**\n"
                    "**Merge** - Your clan joins ours under **one** chain of command, like bannermen folding into a greater house.\n"
                    "**Alliance** - Our houses fight together, but **you remain your own house**; the bond is the pact, not shared rule.\n\n"
                    "`%%%%%%%%%%%%`\n"
                    "**What this does *not* grant you**\n\n"
                    "**1. No twin crown**\n"
                    "You will **not** be made **co-owner** of the clan. There is a single ruling line; you follow it - you do not sit beside it as an equal.\n\n"
                    "**2. The war table is not turned by guests**\n"
                    "You will **not** receive **tsbcc war management perms** (**OCW perms**). "
                    "Who may move armies in our wars is chosen by leadership - **merging or allying does not unlock that chamber**.\n\n"
                    "**3. The council's word is final**\n"
                    "**Leadership hierarchy remains absolute.** Ranks, duties, and how we stand in the field are decided by those who hold the seat - "
                    "not debated here as if the small council were in session with rivals.\n\n"
                    "`%%%%%%%%%%%%`\n"
                    "**What happens next**\n"
                    "Staff will read your petition. Answer **clearly and honestly** when they ask follow-ups, and **wait** for a ruling - "
                    "good alliances are built on patience, not pings in the night."
                ),
                color=0x4A0E16,
            )
            embed.set_footer(text="Shorekeeper - In the game of clans, know the rules before you play.")
            return embed
        if category_key == "support":
            return discord.Embed(
                title="Support - Guidelines",
                description=(
                    "`---`\n"
                    "**Do not spam ping staff.**\n"
                    "Be respectful at all times.\n"
                    "One issue per ticket when possible."
                ),
                color=0x1E1B2E,
            )
        if category_key == "report":
            return discord.Embed(
                title="Report - Policy",
                description=(
                    "`---`\n"
                    "**False reports may be punishable.**\n"
                    "Provide valid evidence when asked.\n"
                    "Do not misuse this system."
                ),
                color=0x1E1B2E,
            )
        return discord.Embed(
            title="Suggestion - Info",
            description=(
                "`---`\n"
                "Staff may ask follow-up questions.\n"
                "Not every suggestion can be implemented.\n"
                "Thank you for helping improve the server."
            ),
            color=0x1E1B2E,
        )

    async def create_ticket_from_modal(
        self,
        interaction: discord.Interaction,
        category_key: str,
        answers: dict,
    ):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)

        existing = self._user_has_open_ticket(guild, interaction.user.id)
        if existing:
            return await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}",
                ephemeral=True,
            )

        prefix_map = {
            "support": "support",
            "merge": "merge",
            "report": "report",
            "suggestion": "suggestion",
        }
        prefix = prefix_map.get(category_key, "support")
        suffix = random.randint(1000, 9999)
        channel_name = f"{prefix}-{suffix}"

        ticket_roles = self._configured_ticket_roles(guild)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        for role in ticket_roles:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            )

        category = None
        ch = interaction.channel
        if isinstance(ch, discord.TextChannel):
            category = ch.category
        elif isinstance(ch, discord.Thread) and isinstance(ch.parent, discord.TextChannel):
            category = ch.parent.category

        await interaction.response.defer(ephemeral=True, thinking=True)

        ticket_channel = None
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                topic=f"ticket_owner={interaction.user.id}",
                reason=f"Ticket ({category_key}) opened by {interaction.user}",
            )

            answers_embed = self._embed_answers(category_key, answers)
            rules_embed = self._embed_rules(category_key)

            pings = [interaction.user.mention]
            pings.extend(role.mention for role in ticket_roles)

            await ticket_channel.send(
                content=" ".join(pings),
                embeds=[answers_embed, rules_embed],
                view=TicketCloseView(self),
                allowed_mentions=self._ticket_allowed_mentions(interaction.user, ticket_roles),
            )

            await interaction.followup.send(f"Ticket created: {ticket_channel.mention}", ephemeral=True)
        except discord.Forbidden:
            if ticket_channel:
                try:
                    await ticket_channel.delete(reason="Ticket creation failed (forbidden).")
                except Exception:
                    pass
            await interaction.followup.send(
                "Could not create or post in the ticket channel (missing permissions).",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            if ticket_channel:
                try:
                    await ticket_channel.delete(reason="Ticket creation failed (HTTP error).")
                except Exception:
                    pass
            await interaction.followup.send(
                f"Ticket failed ({exc.status}): `{exc.text[:500]}`",
                ephemeral=True,
            )
        except Exception as exc:
            if ticket_channel:
                try:
                    await ticket_channel.delete(reason="Ticket creation failed (unexpected).")
                except Exception:
                    pass
            await interaction.followup.send(
                f"Ticket failed: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    async def close_ticket(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not self._is_ticket_channel(channel):
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not self._can_manage_ticket(interaction.user, channel):
            return await interaction.response.send_message("Only ticket staff or the ticket owner can close this ticket.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, msg = await self.send_transcript_to_logs(channel.guild, interaction.user, channel)
        if not ok:
            return await interaction.followup.send(msg, ephemeral=True)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")

    async def _add_or_remove_ticket_member(self, message: discord.Message, trigger, add: bool):
        channel = message.channel
        if not isinstance(channel, discord.TextChannel) or not self._is_ticket_channel(channel):
            return await message.channel.send("This is not a ticket channel.")
        if not self._can_manage_ticket(message.author, channel, allow_owner=False):
            return await message.channel.send("Only ticket staff can add or remove users.")

        target = trigger["target"]
        if not target and trigger["target_id"]:
            try:
                target = await message.guild.fetch_member(trigger["target_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target = None
        if not target:
            action = "addtoticket" if add else "removefromticket"
            return await message.channel.send(f"Use `@Shorekeeper {action} @user_or_id`.")
        if target.bot:
            return await message.channel.send("Cannot add or remove bots from tickets.")

        if add:
            await channel.set_permissions(
                target,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            )
            return await channel.send(f"{target.mention} has been added to this ticket.")

        owner_id = self._ticket_owner_id_from_topic(channel)
        if owner_id == target.id:
            return await channel.send("You cannot remove the ticket owner.")
        await channel.set_permissions(target, overwrite=None)
        return await channel.send(f"{target.mention} has been removed from this ticket.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return
        if message.author.bot or not message.guild:
            return
        if not self._is_ticket_channel(message.channel):
            return

        keyword = trigger["keyword"]
        if keyword not in {"transcripttk", "closeticket", "deletetk", "addtoticket", "removefromticket"}:
            return

        channel: discord.TextChannel = message.channel
        privileged = self._can_manage_ticket(message.author, channel)

        if keyword == "addtoticket":
            return await self._add_or_remove_ticket_member(message, trigger, add=True)

        if keyword == "removefromticket":
            return await self._add_or_remove_ticket_member(message, trigger, add=False)

        if keyword == "transcripttk":
            if not privileged:
                return await channel.send("No permission.")
            ok, msg = await self.send_transcript_to_logs(message.guild, message.author, channel)
            return await channel.send(msg if ok else f"Transcript failed: {msg}")

        if keyword == "closeticket":
            if not privileged:
                return await channel.send("No permission.")
            ok, msg = await self.send_transcript_to_logs(message.guild, message.author, channel)
            if not ok:
                return await channel.send(f"Close failed: {msg}")
            await channel.delete(reason=f"Ticket closed by {message.author}")
            return

        if keyword == "deletetk":
            if not (is_mod(message.author) or is_owner_id(message.guild.id, message.author.id)):
                return await channel.send("No permission.")
            await channel.delete(reason=f"Ticket deleted by {message.author}")
            return


async def setup(bot):
    await bot.add_cog(TicketCog(bot))
