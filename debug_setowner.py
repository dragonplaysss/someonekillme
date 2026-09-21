#!/usr/bin/env python3

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cogs.core.constants import SOLE_OWNER_ID
from cogs.core.permissions import is_owner_id as core_is_owner_id
from cogs.server_config import is_owner_id as server_is_owner_id

print(f"SOLE_OWNER_ID: {SOLE_OWNER_ID}")
print(f"Type of SOLE_OWNER_ID: {type(SOLE_OWNER_ID)}")

# Test the core permissions function
test_id = 708390973712891976
print(f"\nTesting core permissions is_owner_id with ID: {test_id}")
result = core_is_owner_id(test_id)
print(f"core_is_owner_id({test_id}) = {result}")

# Test the server config function
print(f"\nTesting server config is_owner_id with guild_id=123, user_id={test_id}")
result2 = server_is_owner_id(123, test_id)
print(f"server_is_owner_id(123, {test_id}) = {result2}")

# Test what happens when we call it with just guild_id (user_id=None)
print(f"\nTesting server config is_owner_id with guild_id=123, user_id=None")
result3 = server_is_owner_id(123, None)
print(f"server_is_owner_id(123, None) = {result3}")

# Let's also check the constants in server_config
from cogs.server_config import PANEL_OWNER_ID
print(f"\nPANEL_OWNER_ID: {PANEL_OWNER_ID}")
print(f"Type of PANEL_OWNER_ID: {type(PANEL_OWNER_ID)}")