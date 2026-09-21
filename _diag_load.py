"""Temporary diagnostic: emulate main.py startup without connecting to Discord."""
import asyncio
import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

import main  # noqa: E402


async def go():
    bot = main.MyBot()
    print("=== extensions ===")
    for extension in bot.discover_extensions():
        print("EXT", extension)

    print("=== loading (same loop as setup_hook) ===")
    for cog in bot.discover_extensions():
        try:
            await bot.load_extension(cog)
            print(f"[LOADED] {cog}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAILED] {cog}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    print("=== loaded cogs ===")
    for name, cog in sorted(bot.cogs.items()):
        listeners = [listener for listener, _ in cog.get_listeners()]
        print(f"COG {name} listeners={listeners}")

    print("=== on_message listeners registered on the bot ===")
    print(sorted(getattr(bot, "extra_events", {}).keys()))
    for coro in getattr(bot, "extra_events", {}).get("on_message", []):
        print("  listener", getattr(coro, "__qualname__", coro))


asyncio.run(go())
