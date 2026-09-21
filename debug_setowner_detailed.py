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
        self.sent.append((content, kwargs))

class EmptyCollection:
    async def find_one(self, *_args, **_kwargs):
        return None

# Import the actual functions
from cogs.core.constants import SOLE_OWNER_ID
from cogs.core.permissions import is_owner_id as core_is_owner_id
from cogs.server_config import is_owner_id as server_is_owner_id, is_panel_owner, is_admin, get_guild_config, immunity_reason
from cogs.misc_tools import MiscToolsCog

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

# Test server config function with just guild_id (for panel owner check)
server_result_guild_only = server_is_owner_id(test_guild_id, None)
print(f"cogs.server_config.is_owner_id({test_guild_id}, None) = {server_result_guild_only}")

# Test server config function with just user_id (None, user_id)
server_result_user_only = server_is_owner_id(None, test_author_id)
print(f"cogs.server_config.is_owner_id(None, {test_author_id}) = {server_result_user_only}")

# Test the misc_tools _can_owner_only method
print(f"\nTesting MiscToolsCog._can_owner_only:")

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
    return False

cog._enforce_fun_locks = mock_enforce_fun_locks
cog.afk = EmptyCollection()

# Create test message
message = Message()

# Test _can_owner_only
can_owner = cog._can_owner_only(message)
print(f"cog._can_owner_only(message) = {can_owner}")

# Test what happens if we call the server config function the way it might be called incorrectly
print(f"\nTesting potential issues:")
print(f"is_owner_id(None, {test_author_id}) = {server_is_owner_id(None, test_author_id)}")  # This checks if None is sole owner
print(f"is_owner_id({test_guild_id}, None) = {server_is_owner_id(test_guild_id, None)}")  # This checks if guild_id is sole owner