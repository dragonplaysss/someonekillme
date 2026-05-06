import json
import os

import discord
from discord.ext import commands

from cogs.trigger_parser import parse_shorekeeper_trigger
from cogs.server_config import is_admin


DATA_FILE = "cogs/moderation/data2/seals.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


class Seal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_seal_role(self, guild):
        role = discord.utils.get(
            guild.roles,
            name="sealed"
        )

        if role:
            return role

        return await guild.create_role(
            name="sealed"
        )

    async def seal_member(self, member):
        seal_role = await self.get_seal_role(
            member.guild
        )

        saved_roles = [
            role.id
            for role in member.roles
            if role.name != "@everyone"
            and not role.managed
        ]

        data = load_data()

        data[str(member.id)] = saved_roles

        save_data(data)

        await member.edit(
            roles=[seal_role]
        )

    async def unseal_member(self, member):
        data = load_data()

        saved_roles = data.get(str(member.id))

        if not saved_roles:
            return False

        restored_roles = []

        for role_id in saved_roles:
            role = member.guild.get_role(role_id)

            if role:
                restored_roles.append(role)

        await member.edit(
            roles=restored_roles
        )

        del data[str(member.id)]

        save_data(data)

        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(
            self.bot,
            message,
        )

        if not trigger:
            return

        keyword = trigger["keyword"]

        if keyword not in {
            "seal",
            "unseal",
        }:
            return

        if not is_admin(message.author):
            return await message.channel.send(
                "No permission."
            )

        target = trigger["target"]

        if not target:
            return await message.channel.send(
                "User not found."
            )

        if keyword == "seal":
            try:
                await self.seal_member(target)

                await message.channel.send(
                    f"{target.mention} has been sealed."
                )

            except Exception as e:
                await message.channel.send(
                    f"Seal failed: {e}"
                )

        if keyword == "unseal":
            success = await self.unseal_member(
                target
            )

            if success:
                await message.channel.send(
                    f"{target.mention} has been unsealed."
                )
            else:
                await message.channel.send(
                    "User is not sealed."
                )


async def setup(bot):
    await bot.add_cog(Seal(bot))