import asyncio
import inspect
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable


def atomic_write_json(
    path: str | Path,
    data: object,
    *,
    indent: int | None = 4,
    ensure_ascii: bool = True,
) -> None:
    """Write JSON atomically: temp file in the same directory, then os.replace.

    Prevents truncated/corrupted state files when a write is interrupted, and
    keeps concurrent readers on the previous complete document.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent, ensure_ascii=ensure_ascii)
            handle.write("\n")
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class JsonStore:
    def __init__(self, path: str | Path, default_factory: Callable[[], dict]):
        self.path = Path(path)
        self.default_factory = default_factory
        self._lock = asyncio.Lock()

    async def read(self) -> dict:
        async with self._lock:
            return deepcopy(self._read_unlocked())

    async def update(self, mutator) -> dict:
        async with self._lock:
            data = self._read_unlocked()
            result = mutator(data)
            if inspect.isawaitable(result):
                await result
            self._write_unlocked(data)
            return deepcopy(data)

    def _read_unlocked(self) -> dict:
        if not self.path.exists():
            return deepcopy(self.default_factory())
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            os.replace(self.path, backup)
            return deepcopy(self.default_factory())
        return data if isinstance(data, dict) else deepcopy(self.default_factory())

    def _write_unlocked(self, data: dict) -> None:
        atomic_write_json(self.path, data)
