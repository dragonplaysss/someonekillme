#!/usr/bin/env python3
"""
Debug / repair: remove NUL bytes (\\x00) from files.

Use when Python fails with "source code string cannot contain null bytes",
or after a bad sync/editor glitch.

Examples:
  python scripts/fix_nullbytes.py
  python scripts/fix_nullbytes.py cogs/tickets.py
  python scripts/fix_nullbytes.py cogs --dry-run
  python scripts/fix_nullbytes.py . --all-extensions
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def iter_targets(root: Path, *, all_extensions: bool, glob_pat: str) -> list[Path]:
    if root.is_file():
        return [root]
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or should_skip(p):
            continue
        if all_extensions:
            out.append(p)
        elif fnmatch.fnmatch(p.name, glob_pat):
            out.append(p)
    return out


def fix_file(path: Path, *, dry_run: bool) -> tuple[int, bool]:
    """Returns (nul_count, changed)."""
    raw = path.read_bytes()
    nul_count = raw.count(b"\x00")
    if nul_count == 0:
        return 0, False
    cleaned = raw.replace(b"\x00", b"")
    if not dry_run:
        path.write_bytes(cleaned)
    return nul_count, True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Strip NUL (0x00) bytes from files. Safe binary read/write; no UTF-8 decode."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="Files or directories to scan (default: project root).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="List NUL counts only; do not write files.",
    )
    ap.add_argument(
        "--all-extensions",
        action="store_true",
        help="Under directories, scan every file (not only *.py).",
    )
    ap.add_argument(
        "--glob",
        default="*.py",
        help="Filename glob when scanning dirs (default: *.py). Ignored with --all-extensions.",
    )
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    roots = [Path(p).resolve() for p in args.paths] if args.paths else [project_root]

    scanned = 0
    with_nuls = 0
    total_nuls = 0
    modified = 0

    for root in roots:
        if not root.exists():
            print(f"MISSING: {root}", file=sys.stderr)
            continue
        for path in iter_targets(
            root,
            all_extensions=args.all_extensions,
            glob_pat=args.glob,
        ):
            scanned += 1
            try:
                n, changed = fix_file(path, dry_run=args.dry_run)
            except OSError as exc:
                print(f"ERROR  {path}: {exc}", file=sys.stderr)
                continue
            if n:
                with_nuls += 1
                total_nuls += n
                try:
                    rel = path.relative_to(project_root)
                except ValueError:
                    rel = path
                action = "would fix" if args.dry_run else "fixed"
                print(f"{action:9}  {n:6} NUL  {rel}")
                if changed:
                    modified += 1

    mode = "dry-run" if args.dry_run else "write"
    print(
        f"\nDone ({mode}): scanned {scanned} files, "
        f"{with_nuls} had NUL bytes ({total_nuls} total NULs), "
        f"{modified} file(s) {'would be ' if args.dry_run else ''}updated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
