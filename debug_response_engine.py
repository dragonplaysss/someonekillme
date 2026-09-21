#!/usr/bin/env python3

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from cogs.core.responses import response_engine
    print("Successfully imported response_engine")
    print(f"response_engine type: {type(response_engine)}")

    # Test the error method
    print("\nTesting response_engine.error method:")
    embed = response_engine.error("Access Denied", "Only the sole owner can use this command.")
    print(f"Successfully created embed:")
    print(f"  title: {embed.title!r}")
    print(f"  description: {embed.description!r}")
    print(f"  color: {embed.color!r}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()