#!/usr/bin/env python3

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock the classes as they are in the test
class Message:
    def __init__(self):
        self.author = type("Author", (), {"id": 708390973712891976, "bot": False})()
        self.guild = type("Guild", (), {"id": 123})()
        self.channel = Channel()
        self.mentions = []
        self.reference = None

class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        print(f"Channel.send called with content={content!r}, kwargs={kwargs!r}")
        self.sent.append((content, kwargs))

class EmptyCollection:
    async def find_one(self, *_args, **_kwargs):
        return None

# Import the actual functions
from cogs.core.constants import SOLE_OWNER_ID
from cogs.core.permissions import is_owner_id as core_is_owner_id
from cogs.server_config import is_owner_id as server_is_owner_id, is_panel_owner, is_admin, get_guild_config, immunity_reason, update_guild_config
from cogs.misc_tools import MiscToolsCog
from cogs.trigger_parser import parse_shorekeeper_trigger

print(f"SOLE_OWNER_ID: {SOLE_OWNER_ID}")

# Test the owner ID functions directly
test_author_id = 708390973712891976
test_guild_id = 123

print(f"\nTesting owner ID checks:")
print(f"Author ID: {test_author_id}")
print(f"Guild ID: {test_guild_id}")

# Test core permissions function
core_result = core_is_owner_id(test_author_id)
print(f"cogs.core.permissions.is_owner_id({test_author_id}) = {core_result}")

# Test server config function with both params
server_result_both = server_is_owner_id(test_guild_id, test_author_id)
print(f"cogs.server_config.is_owner_id({test_guild_id}, {test_author_id}) = {server_result_both}")

# Create a mock bot
class MockBot:
    def __init__(self):
        self.user = type("BotUser", (), {"id": 999})()
        self.extensions = {}

mock_bot = MockBot()

# Create the cog instance
cog = MiscToolsCog.__new__(MiscToolsCog)
cog.bot = mock_bot
cog.webhook_cache = {}

# Mock the dependencies
async def mock_enforce_fun_locks(message):
    print("_enforce_fun_locks called, returning False")
    return False

cog._enforce_fun_locks = mock_enforce_fun_locks
cog.afk = EmptyCollection()

# Mock update_guild_config to track calls
updates = []
def mock_update_guild_config(guild_id, updater):
    print(f"update_guild_config called with guild_id={guild_id}, updater={updater}")
    updates.append((guild_id, updater))
    # Actually call the updater with a mock config to see what it does
    class MockConfig:
        def __init__(self):
            self.data = {}
        def setdefault(self, key, default):
            if key not in self.data:
                self.data[key] = default
            return self.data[key]
    mock_config = MockConfig()
    try:
        updater(mock_config)
        print(f"Updater executed successfully, config.data = {mock_config.data}")
        return mock_config.data
    except Exception as e:
        print(f"Updater failed with exception: {e}")
        raise

cog.update_guild_config = mock_update_guild_config

# Mock parse_shorekeeper_trigger to return the test data
def mock_parse_shorekeeper_trigger(_bot, _message):
    print(f"parse_shorekeeper_trigger called with _bot={_bot!r}, _message={_message!r}")
    result = {"keyword": "setowner", "extra": "add 111", "target": None, "args": []}
    print(f"parse_shorekeeper_trigger returning: {result!r}")
    return result

# Patch the functions in the misc_tools module
import cogs.misc_tools
original_parse = cogs.misc_tools.parse_shorekeeper_trigger
original_update = cogs.misc_tools.update_guild_config

cogs.misc_tools.parse_shorekeeper_trigger = mock_parse_shorekeeper_trigger
cogs.misc_tools.update_guild_config = mock_update_guild_config

# Create test message
message = Message()
print(f"\nCreated test message:")
print(f"  author.id = {message.author.id}")
print(f"  guild.id = {message.guild.id}")

# Call the on_message method
print(f"\nCalling cog.on_message(message):")
import asyncio
asyncio.run(cog.on_message(message))

print(f"\nAfter on_message:")
print(f"  updates list = {updates}")
print(f"  channel.sent = {message.channel.sent}")

# Restore original functions
cogs.misc_tools.parse_shorekeeper_trigger = original_parse
cogs.misc_tools.update_guild_config = original_update