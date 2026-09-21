from __future__ import annotations

import random
import re


MAX_FUNLOCK_LENGTH = 1800

BARK_LINES = (
    "bark",
    "woof",
    "arf arf",
    "a very serious woof",
    "the watch-hound has opinions",
    "woof. that is the entire report.",
)

UWU_SUFFIXES = (" uwu", " owo", " >w<", " :3")


def uwuify(text: str, seed: int | None = None) -> str:
    rng = random.Random(seed)
    source = (text or "").strip() or "hello"
    converted = re.sub(r"[rl]", "w", source)
    converted = re.sub(r"[RL]", "W", converted)
    converted = re.sub(r"n([aeiouAEIOU])", r"ny\1", converted)
    converted = re.sub(r"N([aeiouAEIOU])", r"Ny\1", converted)
    result = (converted.strip() + rng.choice(UWU_SUFFIXES)).strip()
    return result[:MAX_FUNLOCK_LENGTH]


def bark_response(seed: int | None = None, target_name: str | None = None) -> str:
    rng = random.Random(seed)
    line = rng.choice(BARK_LINES)
    if target_name:
        extras = (
            f"{line}",
            f"{target_name} has been reduced to a single loyal woof.",
            f"the shore's hound stares at {target_name}. {line}.",
        )
        line = rng.choice(extras)
    return line[:MAX_FUNLOCK_LENGTH]
