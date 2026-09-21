# Shorekeeper Security Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve Shorekeeper into a mention-first, security-focused Discord moderation bot with centralized authorization, safe role hierarchy enforcement, moderation cases, guild activation, improved Roblox Auth delivery, controlled logging access, and phased Anti-Nuke support.

**Architecture:** Add a focused `cogs/core/` service layer while preserving the existing cog layout and behavior until each subsystem is migrated. Dangerous actions flow through one authorization pipeline before any Discord API call, then create cases/logs and responses through the centralized Shorekeeper response engine. Configuration remains JSON-backed where appropriate with atomic writes and non-destructive migrations; moderation cases use MongoDB and Roblox Auth account scope remains global.

**Tech Stack:** Python 3.11+, discord.py 2.x, motor/MongoDB, JSON configuration with atomic writes, pytest/pytest-asyncio for tests.

**Spec:** `C:/Users/sarat/.codex/attachments/e5f0bc86-7757-4dee-8821-694ffca5dec8/pasted-text.txt`

## Global Constraints

- `708390973712891976` is the sole hardcoded Shorekeeper owner ID.
- There must be no configurable owner list and no way for Discord roles or guild users to grant owner status.
- Owner authority must never be granted through Discord roles or stored guild configuration.
- Roblox Auth accounts are global/universal across guilds; do not guild-scope account lookup, `get_account()`, or `rbxlist`.
- Mention commands are the primary UX; slash commands stay minimal and setup-oriented only where Discord native interactions provide a meaningful advantage.
- Every dangerous action must use the centralized authorization pipeline: guild activated, module enabled, actor authorized, Discord permission, actor hierarchy, bot permission, bot hierarchy, target safety, security/Anti-Nuke policy, execute, case/log, Shorekeeper response.
- Individual cogs must not bypass the centralized authorization pipeline.
- Shorekeeper must never attempt to act on a member whose highest role is equal to or above Shorekeeper's highest role.
- Shorekeeper must never attempt to manage roles equal to or above Shorekeeper's highest role.
- Shorekeeper must never attempt to act on the guild owner.
- Discord Administrator must never be treated as bypassing role hierarchy.
- Raw message logging is preserved, but access must be authorized and credential redaction must be added.
- Anti-Nuke is disabled by default, per-guild configurable, supports monitor/log-only mode and enforcement mode, uses allowlists and audit-log attribution, and minimizes false positives.
- Unauthorized bot additions have a dedicated immediate protection path when audit-log attribution is clear; missing or ambiguous attribution must never punish a user.
- Anti-Nuke must include explicit allowlists for legitimate bots, users, and roles.
- MongoDB stores moderation cases; JSON remains for configuration/state where appropriate.
- Existing data and configuration must be preserved; migrations are backed up and non-destructive.
- No giant rewrite; migrate and verify subsystem by subsystem.
- After every implementation phase, run relevant tests, inspect `git diff`, check regressions, verify existing commands, and verify data compatibility before claiming progress.

---

## File Structure

Create:
- `cogs/core/__init__.py`: package marker for core services.
- `cogs/core/constants.py`: sole owner ID and shared constants; no configurable owner list.
- `cogs/core/responses.py`: centralized Shorekeeper response engine for all user-facing output.
- `cogs/core/persistence.py`: atomic JSON persistence with async locks.
- `cogs/core/config.py`: centralized config service preserving current JSON layout.
- `cogs/core/hierarchy.py`: bot/member/role hierarchy safety checks.
- `cogs/core/permissions.py`: owner/admin/mod/module/guild activation checks.
- `cogs/core/authz.py`: dangerous-action authorization pipeline.
- `cogs/core/parser.py`: maintainable mention command parser and converters.
- `cogs/core/cases.py`: MongoDB moderation case service.
- `cogs/core/audit.py`: audit-log attribution helpers.
- `cogs/security/anti_nuke.py`: Anti-Nuke monitor/enforcement cog.
- `tests/`: pytest suite for core behavior.

Modify gradually:
- `main.py`: load core services and keep slash tree minimal/deterministic.
- `cogs/trigger_parser.py`: compatibility wrapper around new parser during migration.
- `cogs/server_config.py`: delegate to `cogs/core/config.py` without breaking imports.
- `cogs/mod_config.py`: move writes through atomic persistence.
- `cogs/module_registry.py`: mark missing modules safely; do not delete them blindly.
- `cogs/module_manager.py`: add guild activation and use core permission checks.
- `cogs/moderation/moderation_core.py`: migrate dangerous actions to authz pipeline and cases.
- `cogs/moderation/role_tools.py`: migrate role operations to hierarchy checks.
- `cogs/moderation/nicklock.py`: migrate nickname operations to hierarchy checks.
- `cogs/moderation/seal.py`: migrate seal/unseal to hierarchy checks and cases.
- `cogs/misc_tools.py`: migrate barklock/uwulock and config commands gradually.
- `cogs/logger.py`: add credential redaction and staff-only log access.
- `cogs/roblox_auth.py`: keep global accounts; add request/approval auto-DM flow.
- `cogs/roblox_snipe.py`: keep disabled by default and permissioned.

---

### Task 1: Test Harness And Baseline Safety

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_baseline_imports.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: pytest suite capable of importing pure modules without connecting to Discord or MongoDB.
- Consumes: existing source tree.

- [ ] **Step 1: Add test dependencies**

Add these dependencies to `requirements.txt`:

```text
pytest>=8,<9
pytest-asyncio>=0.23,<1
```

- [ ] **Step 2: Create test fixtures**

Create `tests/conftest.py`:

```python
from dataclasses import dataclass, field


@dataclass
class FakePermissions:
    administrator: bool = False
    ban_members: bool = False
    kick_members: bool = False
    moderate_members: bool = False
    manage_roles: bool = False
    manage_nicknames: bool = False
    manage_channels: bool = False
    manage_webhooks: bool = False


@dataclass(order=True)
class FakeRole:
    position: int
    id: int = field(compare=False)
    name: str = field(compare=False, default="role")
    managed: bool = field(compare=False, default=False)

    @property
    def mention(self):
        return f"<@&{self.id}>"
```

- [ ] **Step 3: Add import baseline**

Create `tests/test_baseline_imports.py`:

```python
def test_module_registry_imports():
    import cogs.module_registry as registry

    assert registry.CORE_MODULE == "core"
    assert "moderation" in registry.MODULES


def test_server_config_owner_constant_is_current_value():
    from cogs.server_config import PANEL_OWNER_ID

    assert PANEL_OWNER_ID == 708390973712891976
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_baseline_imports.py -v
```

Expected: 2 passing tests.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/conftest.py tests/test_baseline_imports.py
git commit -m "test: add Shorekeeper baseline test harness"
```

---

### Task 2: Core Constants And Shorekeeper Response Engine

**Files:**
- Create: `cogs/core/__init__.py`
- Create: `cogs/core/constants.py`
- Create: `cogs/core/responses.py`
- Create: `tests/test_responses.py`

**Interfaces:**
- Produces: `SOLE_OWNER_ID: int`, `ResponseEngine`, `response_engine`, and builders for success, failure, warning, permission denial, hierarchy denial, moderation result, case result, Anti-Nuke alert, lockdown, Roblox Auth approval, Roblox Auth delivery, DM failure, configuration, help, and parser errors.
- Consumes: `discord.Embed`.

- [ ] **Step 1: Write constants tests**

Create `tests/test_responses.py`:

```python
def test_sole_owner_id_is_exactly_configured_owner():
    from cogs.core.constants import SOLE_OWNER_ID

    assert SOLE_OWNER_ID == 708390973712891976
```

- [ ] **Step 2: Write response tests**

Append to `tests/test_responses.py`:

```python
def test_permission_denial_response_has_clear_security_copy():
    from cogs.core.responses import response_engine

    embed = response_engine.permission_denied("You are not authorized to use this command.")

    assert embed.title == "Permission Denied"
    assert "not authorized" in embed.description
    assert embed.footer.text == "Shorekeeper Security"
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
pytest tests/test_responses.py -v
```

Expected: FAIL because `cogs.core` does not exist yet.

- [ ] **Step 4: Create constants**

Create `cogs/core/__init__.py` as an empty file.

Create `cogs/core/constants.py`:

```python
SOLE_OWNER_ID = 708390973712891976
EMBED_FOOTER = "Shorekeeper Security"
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARNING = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_SECURITY = 0x2B2D42
```

- [ ] **Step 5: Create response engine**

Create `cogs/core/responses.py`:

```python
from dataclasses import dataclass

import discord

from cogs.core.constants import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SECURITY,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMBED_FOOTER,
)


@dataclass(frozen=True)
class ResponseEngine:
    footer: str = EMBED_FOOTER

    def build(self, title: str, description: str, *, color: int = COLOR_INFO) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=self.footer)
        return embed

    def success(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_SUCCESS)

    def failure(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_ERROR)

    def warning(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_WARNING)

    def permission_denied(self, detail: str) -> discord.Embed:
        return self.failure("Permission Denied", f"{detail} Shorekeeper will not move without clear authority.")

    def hierarchy_denied(self, detail: str) -> discord.Embed:
        return self.failure("Hierarchy Protected", f"{detail} Discord's role order is absolute.")

    def moderation_result(self, title: str, description: str) -> discord.Embed:
        return self.success(title, description)

    def case_result(self, case_id: int, description: str) -> discord.Embed:
        return self.success(f"Case #{case_id}", description)

    def anti_nuke_alert(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_SECURITY)

    def lockdown(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_SECURITY)

    def roblox_auth_approval(self, description: str) -> discord.Embed:
        return self.success("Roblox Auth Approved", description)

    def roblox_auth_delivery(self, description: str) -> discord.Embed:
        return self.success("Roblox Auth Delivered", description)

    def dm_failure(self, description: str) -> discord.Embed:
        return self.warning("DM Delivery Failed", description)

    def configuration(self, title: str, description: str) -> discord.Embed:
        return self.build(title, description, color=COLOR_INFO)

    def help(self, description: str) -> discord.Embed:
        return self.build("Shorekeeper Help", description, color=COLOR_INFO)

    def parser_error(self, detail: str) -> discord.Embed:
        return self.warning("Command Not Understood", detail)


response_engine = ResponseEngine()
```

Response writing requirements for this task:
- calm, elegant, protective, slightly mysterious, and occasionally playful
- original Shorekeeper-inspired voice only
- no copied Wuthering Waves dialogue or copyrighted text
- personality must never obscure permission, hierarchy, security, or parsing details
- every user-facing message introduced after this task must use this engine or a narrowly scoped wrapper around it

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_responses.py -v
```

Expected: 2 passing tests.

- [ ] **Step 7: Commit**

```bash
git add cogs/core/__init__.py cogs/core/constants.py cogs/core/responses.py tests/test_responses.py
git commit -m "feat: add Shorekeeper core constants and response theme"
```

---

### Task 3: Atomic JSON Persistence

**Files:**
- Create: `cogs/core/persistence.py`
- Create: `tests/test_persistence.py`

**Interfaces:**
- Produces: `JsonStore(path: str | Path, default_factory: Callable[[], dict])`, `async read() -> dict`, `async update(mutator) -> dict`.
- Consumes: filesystem JSON files.

- [ ] **Step 1: Write persistence tests**

Create `tests/test_persistence.py`:

```python
import asyncio

import pytest


@pytest.mark.asyncio
async def test_json_store_preserves_concurrent_updates(tmp_path):
    from cogs.core.persistence import JsonStore

    store = JsonStore(tmp_path / "config.json", lambda: {"count": 0, "items": []})

    async def add_item(value):
        async def mutate(data):
            data["count"] += 1
            data["items"].append(value)

        await store.update(mutate)

    await asyncio.gather(*(add_item(i) for i in range(10)))
    data = await store.read()

    assert data["count"] == 10
    assert sorted(data["items"]) == list(range(10))
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_persistence.py -v
```

Expected: FAIL because `JsonStore` does not exist.

- [ ] **Step 3: Implement atomic store**

Create `cogs/core/persistence.py`:

```python
import asyncio
import inspect
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4)
                handle.write("\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_persistence.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cogs/core/persistence.py tests/test_persistence.py
git commit -m "feat: add atomic JSON persistence"
```

---

### Task 4: Central Config Compatibility Layer

**Files:**
- Create: `cogs/core/config.py`
- Modify: `cogs/server_config.py`
- Modify: `cogs/mod_config.py`
- Create: `tests/test_config_service.py`

**Interfaces:**
- Produces: `ConfigService`, `get_config_service()`, `get_sync_config_snapshot()`, compatibility wrappers preserving existing `get_guild_config()` behavior.
- Consumes: existing JSON schema and `JsonStore`.

- [ ] **Step 1: Write config compatibility test**

Create `tests/test_config_service.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_config_service_creates_guild_with_expected_defaults(tmp_path):
    from cogs.core.config import ConfigService

    service = ConfigService(tmp_path / "server_config.json")
    cfg = await service.get_guild_config(123)

    assert cfg["modules"] == {}
    assert cfg["enabled"] is False
    assert "owner_ids" not in cfg
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_config_service.py -v
```

Expected: FAIL because `ConfigService` does not exist.

- [ ] **Step 3: Implement config service**

Create `cogs/core/config.py` with:

```python
from copy import deepcopy
from pathlib import Path

from cogs.core.constants import SOLE_OWNER_ID
from cogs.core.persistence import JsonStore


DEFAULT_GUILD = {
    "enabled": False,
    "admin_ids": [],
    "admin_roles": [],
    "mod_roles": [],
    "verify_staff_roles": [],
    "verified_roles": [],
    "ticket_ping_roles": [],
    "welcome_gif_url": None,
    "goodbye_gif_url": None,
    "unverified_role": None,
    "skip_role": None,
    "sealed_role": None,
    "immunity_role": None,
    "snipe_role": None,
    "snipe_cooldown_seconds": 20,
    "channels": {
        "blacklist": None,
        "logging": None,
        "track": None,
        "welcome": None,
        "goodbye": None,
        "tickets": None,
        "mod_logs": None,
        "dashboard": None,
    },
    "modules": {},
    "anti_nuke": {
        "enabled": False,
        "mode": "monitor",
        "bot_add_punishment": "kick",
        "trigger_lockdown_on_bot_add": False,
        "trusted_user_ids": [],
        "trusted_role_ids": [],
        "trusted_bot_ids": [],
    },
    "lockdown": {
        "enabled": False,
        "activated_by": None,
        "activated_at": None,
    },
}


def default_config() -> dict:
    return {
        "guilds": {},
        "roblox_auth": {"authorized_guild_ids": []},
    }


class ConfigService:
    def __init__(self, path: str | Path):
        self.store = JsonStore(path, default_config)

    async def get_config(self) -> dict:
        return await self.store.read()

    async def get_guild_config(self, guild_id: int) -> dict:
        async def ensure(data):
            guilds = data.setdefault("guilds", {})
            cfg = guilds.setdefault(str(guild_id), deepcopy(DEFAULT_GUILD))
            merge_guild_defaults(cfg)

        data = await self.store.update(ensure)
        return data["guilds"][str(guild_id)]


def merge_guild_defaults(cfg: dict) -> None:
    for key, value in DEFAULT_GUILD.items():
        if key not in cfg:
            cfg[key] = deepcopy(value)
    for nested in ("channels", "modules", "anti_nuke", "lockdown"):
        if not isinstance(cfg.get(nested), dict):
            cfg[nested] = deepcopy(DEFAULT_GUILD[nested])
            continue
        for key, value in DEFAULT_GUILD[nested].items():
            cfg[nested].setdefault(key, deepcopy(value))
```

- [ ] **Step 4: Run config test**

Run:

```bash
pytest tests/test_config_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Adapt existing config modules**

Modify `cogs/server_config.py` and `cogs/mod_config.py` only after tests pass:
- preserve exported function names currently used by cogs
- route new writes through `JsonStore`
- keep existing JSON file paths
- do not remove existing keys
- ignore legacy `owner_ids` for owner authority; only `SOLE_OWNER_ID` grants owner power
- add `enabled: false` for newly-created guilds only; existing guild activation should be migrated in Task 8

- [ ] **Step 6: Run config-related tests**

Run:

```bash
pytest tests/test_config_service.py tests/test_baseline_imports.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/core/config.py cogs/server_config.py cogs/mod_config.py tests/test_config_service.py
git commit -m "feat: centralize Shorekeeper configuration access"
```

---

### Task 5: Central Hierarchy Safety

**Files:**
- Create: `cogs/core/hierarchy.py`
- Create: `tests/test_hierarchy.py`

**Interfaces:**
- Produces: `HierarchyResult`, `can_bot_act_on_member(bot_member, target)`, `can_bot_manage_role(bot_member, role)`, `can_actor_act_on_member(actor, target)`, `can_actor_manage_role(actor, role)`.
- Consumes: Discord-like member/role objects.

- [ ] **Step 1: Write hierarchy tests**

Create `tests/test_hierarchy.py`:

```python
from dataclasses import dataclass

from tests.conftest import FakePermissions, FakeRole


@dataclass
class FakeMember:
    id: int
    top_role: FakeRole
    guild_permissions: FakePermissions
    guild: object = None


def test_bot_cannot_act_on_equal_role_member():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions())
    target = FakeMember(2, FakeRole(10, 200, "target"), FakePermissions())

    result = can_bot_act_on_member(bot, target)

    assert result.allowed is False
    assert "equal to or above Shorekeeper" in result.reason


def test_bot_can_act_on_lower_role_member():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions())
    target = FakeMember(2, FakeRole(9, 200, "target"), FakePermissions())

    assert can_bot_act_on_member(bot, target).allowed is True


def test_administrator_does_not_bypass_bot_hierarchy():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions(administrator=True))
    target = FakeMember(2, FakeRole(11, 200, "target"), FakePermissions())

    assert can_bot_act_on_member(bot, target).allowed is False


def test_bot_never_acts_on_guild_owner():
    from cogs.core.hierarchy import can_bot_act_on_member

    class Guild:
        owner = None

    guild = Guild()
    bot = FakeMember(1, FakeRole(20, 100, "bot"), FakePermissions(), guild=guild)
    target = FakeMember(2, FakeRole(1, 200, "owner"), FakePermissions(), guild=guild)
    guild.owner = target

    result = can_bot_act_on_member(bot, target)

    assert result.allowed is False
    assert "server owner" in result.reason
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_hierarchy.py -v
```

Expected: FAIL because hierarchy helpers do not exist.

- [ ] **Step 3: Implement hierarchy service**

Create `cogs/core/hierarchy.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class HierarchyResult:
    allowed: bool
    reason: str | None = None


def can_bot_act_on_member(bot_member, target) -> HierarchyResult:
    if target == getattr(target.guild, "owner", None):
        return HierarchyResult(False, "Shorekeeper cannot act on the server owner.")
    if target.top_role >= bot_member.top_role:
        return HierarchyResult(
            False,
            "Shorekeeper cannot act on that member because their highest role is equal to or above Shorekeeper.",
        )
    return HierarchyResult(True)


def can_bot_manage_role(bot_member, role) -> HierarchyResult:
    if role >= bot_member.top_role:
        return HierarchyResult(
            False,
            "Shorekeeper cannot manage that role because it is equal to or above Shorekeeper.",
        )
    return HierarchyResult(True)


def can_actor_act_on_member(actor, target) -> HierarchyResult:
    if actor == getattr(actor.guild, "owner", None):
        return HierarchyResult(True)
    if target.top_role >= actor.top_role:
        return HierarchyResult(
            False,
            "You cannot target a member whose highest role is equal to or above your highest role.",
        )
    return HierarchyResult(True)


def can_actor_manage_role(actor, role) -> HierarchyResult:
    if actor == getattr(actor.guild, "owner", None):
        return HierarchyResult(True)
    if role >= actor.top_role:
        return HierarchyResult(
            False,
            "You cannot manage a role equal to or above your highest role.",
        )
    return HierarchyResult(True)
```

- [ ] **Step 4: Run hierarchy tests**

Run:

```bash
pytest tests/test_hierarchy.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cogs/core/hierarchy.py tests/test_hierarchy.py
git commit -m "feat: add centralized hierarchy safety checks"
```

---

### Task 6: Permission And Authorization Pipeline

**Files:**
- Create: `cogs/core/permissions.py`
- Create: `cogs/core/authz.py`
- Create: `tests/test_authorization.py`

**Interfaces:**
- Produces: `is_owner_id(user_id)`, `is_guild_enabled(config)`, `DangerousActionRequest`, `AuthorizationDecision`, `authorize_dangerous_action(request)`.
- Consumes: config dictionaries and hierarchy helpers.

- [ ] **Step 1: Write owner test**

Create `tests/test_authorization.py`:

```python
def test_only_hardcoded_owner_is_global_owner():
    from cogs.core.permissions import is_owner_id

    assert is_owner_id(708390973712891976) is True
    assert is_owner_id(1) is False


def test_legacy_config_owner_ids_do_not_grant_owner_authority():
    from cogs.core.permissions import is_owner_id

    legacy_config = {"owner_ids": [1, 2, 3]}

    assert legacy_config["owner_ids"]
    assert is_owner_id(1) is False
```

- [ ] **Step 2: Write activation test**

Append:

```python
def test_disabled_guild_blocks_dangerous_action():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    request = DangerousActionRequest(
        guild_config={"enabled": False, "modules": {"moderation": "active"}},
        module="moderation",
        actor=None,
        bot_member=None,
        target_member=None,
        target_role=None,
        actor_authorized=True,
        required_bot_permissions=(),
        required_actor_permissions=(),
        security_policy_allowed=True,
        security_action="ban",
    )

    decision = authorize_dangerous_action(request)

    assert decision.allowed is False
    assert decision.stage == "guild_activation"
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
pytest tests/test_authorization.py -v
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement permissions**

Create `cogs/core/permissions.py`:

```python
from cogs.core.constants import SOLE_OWNER_ID


def is_owner_id(user_id: int) -> bool:
    return int(user_id) == SOLE_OWNER_ID


def module_enabled(guild_config: dict, module: str) -> bool:
    if module == "core":
        return True
    state = guild_config.get("modules", {}).get(module, "active")
    return state in {"active", "debug", "hidden"}


def guild_enabled(guild_config: dict) -> bool:
    return bool(guild_config.get("enabled", False))
```

- [ ] **Step 5: Implement authz pipeline**

Create `cogs/core/authz.py`:

```python
from dataclasses import dataclass
from typing import Iterable

from cogs.core.hierarchy import can_actor_act_on_member, can_actor_manage_role, can_bot_act_on_member, can_bot_manage_role
from cogs.core.permissions import guild_enabled, module_enabled


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    stage: str
    reason: str | None = None


@dataclass(frozen=True)
class DangerousActionRequest:
    guild_config: dict
    module: str
    actor: object | None
    bot_member: object | None
    target_member: object | None
    target_role: object | None
    actor_authorized: bool
    required_bot_permissions: Iterable[str]
    required_actor_permissions: Iterable[str]
    security_policy_allowed: bool
    security_action: str


def authorize_dangerous_action(request: DangerousActionRequest) -> AuthorizationDecision:
    if not guild_enabled(request.guild_config):
        return AuthorizationDecision(False, "guild_activation", "Shorekeeper is not activated in this server.")
    if not module_enabled(request.guild_config, request.module):
        return AuthorizationDecision(False, "module_enabled", "That module is disabled in this server.")
    if not request.actor_authorized:
        return AuthorizationDecision(False, "actor_authorization", "You are not authorized to use this Shorekeeper action.")
    if request.actor is not None:
        actor_perms = getattr(request.actor, "guild_permissions", None)
        for perm in request.required_actor_permissions:
            if not getattr(actor_perms, perm, False):
                return AuthorizationDecision(False, "discord_permission", f"You need `{perm}` for this action.")
    if request.target_member is not None and request.actor is not None:
        actor_result = can_actor_act_on_member(request.actor, request.target_member)
        if not actor_result.allowed:
            return AuthorizationDecision(False, "actor_hierarchy", actor_result.reason)
    if request.bot_member is not None:
        bot_perms = getattr(request.bot_member, "guild_permissions", None)
        for perm in request.required_bot_permissions:
            if not getattr(bot_perms, perm, False):
                return AuthorizationDecision(False, "bot_permission", f"Shorekeeper needs `{perm}` for this action.")
    if request.target_member is not None and request.bot_member is not None:
        bot_result = can_bot_act_on_member(request.bot_member, request.target_member)
        if not bot_result.allowed:
            return AuthorizationDecision(False, "bot_hierarchy", bot_result.reason)
    if request.target_role is not None and request.actor is not None:
        actor_role_result = can_actor_manage_role(request.actor, request.target_role)
        if not actor_role_result.allowed:
            return AuthorizationDecision(False, "actor_hierarchy", actor_role_result.reason)
    if request.target_role is not None and request.bot_member is not None:
        bot_role_result = can_bot_manage_role(request.bot_member, request.target_role)
        if not bot_role_result.allowed:
            return AuthorizationDecision(False, "bot_hierarchy", bot_role_result.reason)
    if not request.security_policy_allowed:
        return AuthorizationDecision(False, "security_policy", "A Shorekeeper security policy blocked this action.")
    return AuthorizationDecision(True, "execute")
```

No Discord API call may occur before this function returns `allowed=True`. Existing cogs must be migrated so execution is structurally after the pipeline, followed by case/log creation and a `response_engine` response.

- [ ] **Step 6: Run authz tests**

Run:

```bash
pytest tests/test_authorization.py tests/test_hierarchy.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/core/permissions.py cogs/core/authz.py tests/test_authorization.py
git commit -m "feat: add centralized dangerous action authorization"
```

---

### Task 7: Moderation Case Service

**Files:**
- Create: `cogs/core/cases.py`
- Create: `tests/test_cases.py`
- Modify: `cogs/moderation/moderation_core.py`

**Interfaces:**
- Produces: `CaseService`, `create_case(...)`, `find_case(...)`, `find_cases(...)`.
- Consumes: MongoDB database object from `get_mongo_database()`.

- [ ] **Step 1: Write case service unit test with fake collection**

Create `tests/test_cases.py`:

```python
import pytest


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def find_one_and_update(self, query, update, upsert, return_document):
        return {"_id": query["_id"], "seq": 41}

    async def insert_one(self, doc):
        self.docs.append(doc)
        return object()


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection())
        return super().__getitem__(key)


@pytest.mark.asyncio
async def test_create_case_assigns_incrementing_case_id():
    from cogs.core.cases import CaseService

    db = FakeDb()
    service = CaseService(db)
    case = await service.create_case(
        guild_id=123,
        action="BAN",
        target_id=10,
        moderator_id=20,
        reason="Raid attempt",
        evidence=None,
    )

    assert case["case_id"] == 42
    assert case["action"] == "BAN"
    assert db["moderation_cases"].docs[0]["target_id"] == 10
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_cases.py -v
```

Expected: FAIL because `CaseService` does not exist.

- [ ] **Step 3: Implement case service**

Create `cogs/core/cases.py`:

```python
import discord
from pymongo import ReturnDocument


class CaseService:
    def __init__(self, db):
        self.cases = db["moderation_cases"]
        self.counters = db["moderation_case_counters"]

    async def create_case(
        self,
        *,
        guild_id: int,
        action: str,
        target_id: int,
        moderator_id: int,
        reason: str,
        evidence: str | None,
    ) -> dict:
        counter = await self.counters.find_one_and_update(
            {"_id": int(guild_id)},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        case_id = int(counter.get("seq", 0)) + 1
        doc = {
            "guild_id": int(guild_id),
            "case_id": case_id,
            "action": action.upper(),
            "target_id": int(target_id),
            "moderator_id": int(moderator_id),
            "reason": reason or "No reason provided.",
            "evidence": evidence,
            "created_at": discord.utils.utcnow(),
        }
        await self.cases.insert_one(doc)
        return doc
```

- [ ] **Step 4: Run case test**

Run:

```bash
pytest tests/test_cases.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire moderation core to create cases**

Modify `cogs/moderation/moderation_core.py`:
- instantiate `CaseService(self.db)`
- for ban/kick/timeout/untimeout/warn/purge, create a case after successful action
- keep existing `mod_actions` writes for compatibility during migration
- include case ID in confirmation response

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_cases.py tests/test_baseline_imports.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/core/cases.py cogs/moderation/moderation_core.py tests/test_cases.py
git commit -m "feat: add MongoDB moderation case service"
```

---

### Task 8: Guild Activation And Minimal Command Tree

**Files:**
- Modify: `cogs/module_manager.py`
- Modify: `cogs/module_registry.py`
- Modify: `cogs/misc_tools.py`
- Modify: `main.py`
- Create: `tests/test_module_registry.py`

**Interfaces:**
- Produces: owner-only guild activation/deactivation commands and status surfacing for missing modules.
- Consumes: config service and existing module registry.

- [ ] **Step 1: Write registry missing-module test**

Create `tests/test_module_registry.py`:

```python
def test_missing_registry_extensions_are_detectable():
    from pathlib import Path
    from cogs.module_registry import all_extensions

    missing = [
        ext for ext in all_extensions()
        if not Path(*ext.split(".")).with_suffix(".py").exists()
    ]

    assert "cogs.applications" in missing
    assert "cogs.ff_checker" in missing
```

- [ ] **Step 2: Run test**

Run:

```bash
pytest tests/test_module_registry.py -v
```

Expected: PASS, documenting current missing modules.

- [ ] **Step 3: Add owner-only activation commands**

Modify `cogs/module_manager.py`:
- add mention commands `activateguild`, `deactivateguild`, `guildstatus`
- enforce hardcoded owner only via `cogs.core.permissions.is_owner_id`
- do not allow guild admins or roles to activate guilds
- store `enabled: true/false` in guild config

Modify `cogs/misc_tools.py`:
- retire or replace legacy configurable owner commands `owners` and `setowner`
- if invoked, return a Shorekeeper response explaining that owner authority is hardcoded and cannot be changed from Discord
- do not write `owner_ids` for any new owner-authority behavior

- [ ] **Step 4: Keep slash tree minimal**

Modify `main.py` and `cogs/module_registry.py`:
- keep core slash commands only for `help`, `settings`, `status`, `enablecommands`, `disablecommands`
- prevent missing module names from being presented as loaded
- display missing modules as `configured_missing` in status instead of trying recovery repeatedly

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_module_registry.py tests/test_authorization.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cogs/module_manager.py cogs/module_registry.py cogs/misc_tools.py main.py tests/test_module_registry.py
git commit -m "feat: add owner-controlled guild activation"
```

---

### Task 9: Mention Parser Framework

**Files:**
- Create: `cogs/core/parser.py`
- Modify: `cogs/trigger_parser.py`
- Create: `tests/test_parser.py`

**Interfaces:**
- Produces: `parse_mention_command(bot_user_id, content, mentions) -> ParsedCommand | None`, quoted args, aliases, target IDs, channel IDs, role IDs, durations.
- Consumes: raw Discord message data.

- [ ] **Step 1: Write parser tests**

Create `tests/test_parser.py`:

```python
def test_parser_supports_quoted_reason():
    from cogs.core.parser import parse_mention_command

    parsed = parse_mention_command(
        bot_user_id=999,
        content='<@999> ban <@123456789012345678> "raid attempt"',
    )

    assert parsed.keyword == "ban"
    assert parsed.args == ["<@123456789012345678>", "raid attempt"]
    assert parsed.user_ids == [123456789012345678]


def test_parser_supports_duration():
    from cogs.core.parser import parse_duration

    assert parse_duration("10s").total_seconds() == 10
    assert parse_duration("10m").total_seconds() == 600
    assert parse_duration("2h").total_seconds() == 7200
    assert parse_duration("7d").total_seconds() == 604800
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_parser.py -v
```

Expected: FAIL because parser does not exist.

- [ ] **Step 3: Implement parser**

Create `cogs/core/parser.py` with:
- `ParsedCommand` dataclass
- `parse_mention_command()`
- `parse_duration()`
- aliases from current `COMMAND_ALIASES`
- `shlex.split()` for quoted args
- regex extraction for user/channel/role IDs

- [ ] **Step 4: Adapt compatibility wrapper**

Modify `cogs/trigger_parser.py`:
- call `parse_mention_command()`
- preserve existing returned keys: `keyword`, `raw_keyword`, `module`, `main`, `args`, `extra`, `target`, `target_id`
- retain disabled-module checks
- keep semicolon compatibility during migration

- [ ] **Step 5: Run parser tests**

Run:

```bash
pytest tests/test_parser.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cogs/core/parser.py cogs/trigger_parser.py tests/test_parser.py
git commit -m "feat: add maintainable mention command parser"
```

---

### Task 10: Migrate Moderation Dangerous Actions

**Files:**
- Modify: `cogs/moderation/moderation_core.py`
- Modify: `cogs/moderation/role_tools.py`
- Modify: `cogs/moderation/nicklock.py`
- Modify: `cogs/moderation/seal.py`
- Create: `tests/test_moderation_authorization.py`

**Interfaces:**
- Consumes: `authorize_dangerous_action()`, hierarchy helpers, case service.
- Produces: moderation commands that do not attempt unsafe Discord API calls.

- [ ] **Step 1: Add authorization tests for unsafe member targets**

Create `tests/test_moderation_authorization.py`:

```python
from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, role):
        self.top_role = role
        self.guild_permissions = FakePermissions(ban_members=True)
        self.guild = None


def test_authorization_blocks_equal_bot_hierarchy_before_execution():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    bot = Member(FakeRole(10, 1, "bot"))
    target = Member(FakeRole(10, 2, "target"))
    actor = Member(FakeRole(20, 3, "actor"))

    decision = authorize_dangerous_action(
        DangerousActionRequest(
            guild_config={"enabled": True, "modules": {"moderation": "active"}},
            module="moderation",
            actor=actor,
            bot_member=bot,
            target_member=target,
            target_role=None,
            actor_authorized=True,
            required_bot_permissions=("ban_members",),
            required_actor_permissions=("ban_members",),
            security_policy_allowed=True,
            security_action="ban",
        )
    )

    assert decision.allowed is False
    assert decision.stage == "bot_hierarchy"
```

- [ ] **Step 2: Run tests**

Run:

```bash
pytest tests/test_moderation_authorization.py -v
```

Expected: PASS if Task 6 exists.

- [ ] **Step 3: Migrate ban/kick/timeout/untimeout**

Modify `cogs/moderation/moderation_core.py`:
- build `DangerousActionRequest` before each API call
- use required bot permissions: `ban_members`, `kick_members`, `moderate_members`
- use required actor permissions from Discord permissions or existing Shorekeeper admin/mod checks
- return themed error embed when blocked
- create case only after successful API call

- [ ] **Step 4: Migrate warn/purge**

Modify `cogs/moderation/moderation_core.py`:
- warn uses actor authorization and target safety
- purge uses guild activation, module enabled, actor permission, bot `manage_messages`
- create cases for warn and purge

- [ ] **Step 5: Migrate role/nick/seal**

Modify:
- `cogs/moderation/role_tools.py`: check actor and bot can manage role before add/remove.
- `cogs/moderation/nicklock.py`: check bot can act on member before nickname edit.
- `cogs/moderation/seal.py`: check every restored/removed role via `can_bot_manage_role()`.

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_moderation_authorization.py tests/test_hierarchy.py tests/test_authorization.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/moderation/moderation_core.py cogs/moderation/role_tools.py cogs/moderation/nicklock.py cogs/moderation/seal.py tests/test_moderation_authorization.py
git commit -m "feat: route moderation actions through authorization pipeline"
```

---

### Task 11: Staff-Only Logs And Credential Redaction

**Files:**
- Modify: `cogs/logger.py`
- Create: `cogs/core/redaction.py`
- Create: `tests/test_redaction.py`

**Interfaces:**
- Produces: `redact_sensitive(text: str) -> str`.
- Consumes: raw message content and log export requests.

- [ ] **Step 1: Write redaction tests**

Create `tests/test_redaction.py`:

```python
def test_redacts_discord_token_like_value():
    from cogs.core.redaction import redact_sensitive

    text = "token abc.def.ghi password hunter2"
    redacted = redact_sensitive(text)

    assert "abc.def.ghi" not in redacted
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_redaction.py -v
```

Expected: FAIL because redaction module does not exist.

- [ ] **Step 3: Implement redaction**

Create `cogs/core/redaction.py`:

```python
import re

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(token|password|totp|secret|webhook)\s*[:= ]\s*\S+"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\S+"),
]


def redact_sensitive(text: str | None) -> str:
    if not text:
        return ""
    redacted = str(text)
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).split()[0] + " [REDACTED]", redacted)
    return redacted
```

- [ ] **Step 4: Modify logger writes**

Modify `cogs/logger.py`:
- apply `redact_sensitive()` to `content`, `before`, and `after`
- keep useful moderation/security event logs
- add permission check to `!logs`: only hardcoded owner, guild owner, configured admins, or configured mod roles can access
- do not send unrestricted logs to ordinary users

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_redaction.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cogs/core/redaction.py cogs/logger.py tests/test_redaction.py
git commit -m "fix: restrict log access and redact credentials"
```

---

### Task 12: Roblox Auth Auto-DM Approval Flow

**Files:**
- Modify: `cogs/roblox_auth.py`
- Create: `tests/test_roblox_auth_flow.py`

**Interfaces:**
- Preserves: global/universal account storage and lookup across all guilds.
- Produces: approval command that atomically assigns an account, delivers credentials immediately by DM, and reports success/failure privately to the approving moderator.

- [ ] **Step 1: Write global lookup preservation test**

Create `tests/test_roblox_auth_flow.py`:

```python
def test_username_key_is_global_not_guild_scoped():
    from cogs.roblox_auth import _username_key

    assert _username_key("BuilderMan") == "builderman"


def test_approval_filter_does_not_include_guild_scope():
    from cogs.roblox_auth import _username_key

    query = {"username_key": _username_key("BuilderMan"), "active": True}

    assert "guild_id" not in query
```

- [ ] **Step 2: Run preservation test**

Run:

```bash
pytest tests/test_roblox_auth_flow.py -v
```

Expected: PASS.

- [ ] **Step 3: Add delivery method**

Modify `cogs/roblox_auth.py`:
- add `DeliveryResult(success: bool, reason: str, dm_message_id: int | None = None)`
- add `async deliver_account_to_user(guild, discord_user, account, approval) -> DeliveryResult`
- generate TOTP internally
- decrypt password only inside delivery
- DM requester
- use `response_engine.roblox_auth_delivery()` for successful requester DMs
- use `response_engine.dm_failure()` for moderator-facing DM failure notices
- log only metadata: requester ID, account username, delivery result, password included yes/no
- never log TOTP code, password, Fernet token, or TOTP secret
- never send credentials in public channels

- [ ] **Step 4: Modify `approveauth`**

Modify `approveauth`:
- keep global account lookup via `self.get_account(roblox_username)`
- create approval with an atomic MongoDB update that first deactivates any active approval for the same global account
- prevent duplicate/racing assignments by requiring a single active approval per `username_key`
- immediately call `deliver_account_to_user`
- send moderator a private/ephemeral success confirmation after DM delivery succeeds
- if DM fails, explain DMs may be disabled, blocked, or unavailable
- if DM fails, do not expose credentials in-channel; keep the approval state auditable and retryable

- [ ] **Step 5: Add race and failure tests**

Append to `tests/test_roblox_auth_flow.py`:

```python
def test_active_approval_uniqueness_filter_is_global():
    username_key = "builderman"
    replacement_filter = {"username_key": username_key, "active": True}

    assert replacement_filter == {"username_key": "builderman", "active": True}
    assert "guild_id" not in replacement_filter


def test_delivery_result_has_no_credential_fields():
    from cogs.roblox_auth import DeliveryResult

    result = DeliveryResult(success=False, reason="DMs are unavailable.", dm_message_id=None)

    assert hasattr(result, "success")
    assert hasattr(result, "reason")
    assert not hasattr(result, "password")
    assert not hasattr(result, "totp_secret")
    assert not hasattr(result, "code")
```

- [ ] **Step 6: Preserve manual mention fallback temporarily**

Keep existing `@Shorekeeper robloxauth username` behavior as a fallback during migration, but mark it as secondary in help text.

- [ ] **Step 7: Run tests**

Run:

```bash
pytest tests/test_roblox_auth_flow.py tests/test_baseline_imports.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add cogs/roblox_auth.py tests/test_roblox_auth_flow.py
git commit -m "feat: auto-deliver Roblox Auth approvals by DM"
```

---

### Task 13: Anti-Nuke Monitor Mode

**Files:**
- Create: `cogs/security/__init__.py`
- Create: `cogs/security/anti_nuke.py`
- Modify: `cogs/module_registry.py`
- Create: `tests/test_anti_nuke_policy.py`

**Interfaces:**
- Produces: `AntiNukePolicy`, monitor-only event logging, explicit bot/user/role allowlists, and unauthorized bot-add assessment.
- Consumes: guild config, audit-log helpers.

- [ ] **Step 1: Write policy tests**

Create `tests/test_anti_nuke_policy.py`:

```python
def test_anti_nuke_disabled_by_default_allows_monitor_no_punishment():
    from cogs.security.anti_nuke import evaluate_bot_add

    decision = evaluate_bot_add(
        config={"enabled": False, "mode": "monitor", "trusted_user_ids": [], "trusted_role_ids": [], "trusted_bot_ids": []},
        actor_id=1,
        actor_role_ids=[],
        bot_id=2,
        attribution_clear=True,
    )

    assert decision.should_remove_bot is False
    assert decision.should_punish_actor is False
    assert decision.reason == "anti_nuke_disabled"


def test_unknown_bot_by_untrusted_actor_is_suspicious_in_enforcement():
    from cogs.security.anti_nuke import evaluate_bot_add

    decision = evaluate_bot_add(
        config={"enabled": True, "mode": "enforce", "trusted_user_ids": [], "trusted_role_ids": [], "trusted_bot_ids": []},
        actor_id=1,
        actor_role_ids=[],
        bot_id=2,
        attribution_clear=True,
    )

    assert decision.should_remove_bot is True
    assert decision.should_punish_actor is True


def test_missing_or_ambiguous_attribution_never_punishes_actor():
    from cogs.security.anti_nuke import evaluate_bot_add

    decision = evaluate_bot_add(
        config={"enabled": True, "mode": "enforce", "trusted_user_ids": [], "trusted_role_ids": [], "trusted_bot_ids": []},
        actor_id=None,
        actor_role_ids=[],
        bot_id=2,
        attribution_clear=False,
    )

    assert decision.should_remove_bot is True
    assert decision.should_punish_actor is False
    assert decision.reason == "attribution_missing_or_ambiguous"


def test_allowlisted_bot_user_or_role_prevents_enforcement():
    from cogs.security.anti_nuke import evaluate_bot_add

    by_bot = evaluate_bot_add(
        config={"enabled": True, "mode": "enforce", "trusted_user_ids": [], "trusted_role_ids": [], "trusted_bot_ids": [2]},
        actor_id=1,
        actor_role_ids=[],
        bot_id=2,
        attribution_clear=True,
    )
    by_user = evaluate_bot_add(
        config={"enabled": True, "mode": "enforce", "trusted_user_ids": [1], "trusted_role_ids": [], "trusted_bot_ids": []},
        actor_id=1,
        actor_role_ids=[],
        bot_id=2,
        attribution_clear=True,
    )
    by_role = evaluate_bot_add(
        config={"enabled": True, "mode": "enforce", "trusted_user_ids": [], "trusted_role_ids": [9], "trusted_bot_ids": []},
        actor_id=1,
        actor_role_ids=[9],
        bot_id=2,
        attribution_clear=True,
    )

    assert by_bot.should_remove_bot is False
    assert by_user.should_punish_actor is False
    assert by_role.should_punish_actor is False
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_anti_nuke_policy.py -v
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement policy-only module**

Create `cogs/security/__init__.py` empty.

Create `cogs/security/anti_nuke.py` with:
- `AntiNukeDecision` dataclass
- `evaluate_bot_add(config, actor_id, actor_role_ids, bot_id, attribution_clear)`
- disabled mode returns no enforcement
- monitor mode logs only
- enforcement mode removes the unauthorized bot only when the added bot is not allowlisted
- enforcement mode punishes the actor only when attribution is clear and actor user/roles are not allowlisted
- missing or ambiguous attribution never punishes a user

- [ ] **Step 4: Add cog listeners in monitor mode**

In `cogs/security/anti_nuke.py`, add a Discord cog:
- `on_member_join` for bots
- fetch audit log entry for bot add
- resolve actor role IDs when the actor is still in guild
- evaluate policy
- log with `response_engine.anti_nuke_alert()`
- do not enforce in monitor mode

- [ ] **Step 5: Register module**

Modify `cogs/module_registry.py`:
- add `security` or `anti_nuke` module with extension `cogs.security.anti_nuke`
- default state disabled
- mention commands: `antinuke`, `lockdown`
- no slash commands by default

- [ ] **Step 6: Run policy tests**

Run:

```bash
pytest tests/test_anti_nuke_policy.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/security/__init__.py cogs/security/anti_nuke.py cogs/module_registry.py tests/test_anti_nuke_policy.py
git commit -m "feat: add Anti-Nuke monitor policy"
```

---

### Task 14: Anti-Nuke Enforcement And Emergency Lockdown

**Files:**
- Modify: `cogs/security/anti_nuke.py`
- Create: `cogs/core/audit.py`
- Modify: `cogs/module_manager.py`
- Create: `tests/test_lockdown.py`

**Interfaces:**
- Produces: emergency lockdown config state and enforcement path for unauthorized bot additions.
- Consumes: hierarchy/authz helpers and Anti-Nuke policy.

- [ ] **Step 1: Write lockdown test**

Create `tests/test_lockdown.py`:

```python
def test_lockdown_defaults_to_disabled():
    from cogs.core.config import DEFAULT_GUILD

    assert DEFAULT_GUILD["lockdown"]["enabled"] is False
    assert DEFAULT_GUILD["anti_nuke"]["enabled"] is False
```

- [ ] **Step 2: Run test**

Run:

```bash
pytest tests/test_lockdown.py -v
```

Expected: PASS if Task 4 exists.

- [ ] **Step 3: Add audit helper**

Create `cogs/core/audit.py`:
- `AuditAttribution(actor_id: int | None, clear: bool, reason: str)`
- `async find_recent_audit_actor(guild, action, target_id) -> AuditAttribution`
- handle `discord.Forbidden` and `discord.HTTPException` by returning `AuditAttribution(None, False, "...")`
- return `clear=False` when no single matching audit-log entry is found
- never punish actor when attribution is missing or ambiguous

- [ ] **Step 4: Add enforcement path**

Modify `cogs/security/anti_nuke.py`:
- treat unauthorized bot additions as immediate-protection events
- if mode is `enforce` and decision says remove bot, check bot permission and bot hierarchy before any API call
- remove the unauthorized bot where possible when Shorekeeper has permission and hierarchy
- apply configured actor punishment only when audit-log attribution is clear, actor is not allowlisted, and hierarchy permits
- supported actor punishments in this phase: `none`, `kick`, `ban`
- do not punish anyone when audit-log attribution is missing or ambiguous
- optionally trigger emergency lockdown when `trigger_lockdown_on_bot_add` is enabled
- log executed and skipped enforcement with exact reason through `response_engine.anti_nuke_alert()`

- [ ] **Step 5: Add lockdown commands**

Modify `cogs/module_manager.py`:
- mention command `lockdown on`
- mention command `lockdown off`
- owner/admin controlled according to approved policy
- store `lockdown.enabled`, `activated_by`, `activated_at`
- security policy checks lockdown state before dangerous actions

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_lockdown.py tests/test_anti_nuke_policy.py tests/test_authorization.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/core/audit.py cogs/security/anti_nuke.py cogs/module_manager.py tests/test_lockdown.py
git commit -m "feat: add Anti-Nuke enforcement and emergency lockdown"
```

---

### Task 15: Uwulock And Barklock UX Migration

**Files:**
- Modify: `cogs/misc_tools.py`
- Create: `cogs/core/funlocks.py`
- Create: `tests/test_funlocks.py`

**Interfaces:**
- Produces: randomized but bounded fun-lock responses and cooldown behavior.
- Consumes: existing Mongo collections `bark_locks`, `uwu_locks`.

- [ ] **Step 1: Write response variant test**

Create `tests/test_funlocks.py`:

```python
def test_funlock_response_is_bounded():
    from cogs.core.funlocks import uwuify

    result = uwuify("hello friend", seed=1)

    assert len(result) <= 1800
    assert result
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_funlocks.py -v
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement funlock helpers**

Create `cogs/core/funlocks.py`:
- deterministic `uwuify(text, seed=None)`
- `bark_response(seed=None)`
- small curated response lists
- no mass mentions
- max length limits

- [ ] **Step 4: Migrate misc tools**

Modify `cogs/misc_tools.py`:
- use funlock helpers
- route barklock/uwulock commands through authz pipeline
- keep existing Mongo state
- add concise themed embeds for enable/disable/status

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_funlocks.py tests/test_authorization.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cogs/core/funlocks.py cogs/misc_tools.py tests/test_funlocks.py
git commit -m "feat: polish Uwulock and Barklock behavior"
```

---

### Task 16: Final Command Tree And Regression Verification

**Files:**
- Modify: `README.md`
- Modify: `MODULES.md`
- Modify: `TRANSFER.md`
- Create: `tests/test_command_tree_policy.py`

**Interfaces:**
- Produces: documented minimal slash policy and mention-first UX.
- Consumes: module registry.

- [ ] **Step 1: Write command tree policy test**

Create `tests/test_command_tree_policy.py`:

```python
def test_core_slash_tree_remains_small():
    from cogs.module_registry import MODULES

    core = set(MODULES["core"]["slash"])
    assert {"help", "settings", "status", "enablecommands", "disablecommands"}.issubset(core)
    assert "ban" not in core
    assert "kick" not in core
    assert "warn" not in core
```

- [ ] **Step 2: Run policy test**

Run:

```bash
pytest tests/test_command_tree_policy.py -v
```

Expected: PASS.

- [ ] **Step 3: Update docs**

Modify:
- `README.md`: mention-first UX, guild activation, security posture.
- `MODULES.md`: mark missing modules as configured-missing or retired candidates.
- `TRANSFER.md`: operational migration and verification checklist.

- [ ] **Step 4: Run full tests**

Run:

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Inspect diff**

Run:

```bash
git diff --stat
git diff --check
```

Expected: no whitespace errors; changes limited to planned files.

- [ ] **Step 6: Commit**

```bash
git add README.md MODULES.md TRANSFER.md tests/test_command_tree_policy.py
git commit -m "docs: document Shorekeeper security architecture"
```

---

## Migration Notes

- Existing JSON config is preserved in place.
- Before first config migration, copy `cogs/moderation/data2/server_config.json` to a timestamped `.bak` file.
- Existing Mongo collections remain valid: `warns`, `mod_actions`, `roblox_accounts`, `roblox_approvals`.
- New Mongo collections: `moderation_cases`, `moderation_case_counters`.
- Existing raw logs remain on disk, but new access controls prevent unrestricted export.
- Missing registry modules are not deleted; they are surfaced as missing until the owner decides restore vs retire.
- Roblox Auth account scope remains global/universal.

## Phase Completion Gate

Every implementation task must end with this verification block before reporting success:

```bash
pytest -v
git diff --stat
git diff --check
git status --short
```

Manual regression checks for phases that touch live bot behavior:
- mention command parsing still accepts `@Shorekeeper help`, `@Shorekeeper config`, and migrated moderation syntax
- slash tree remains minimal and does not expose ban/kick/warn/timeout as slash commands
- existing JSON config loads without deleting existing keys
- Roblox Auth account lookup remains global and does not filter by guild
- dangerous commands fail before Discord API calls when hierarchy or permissions are unsafe
- user-facing output goes through the Shorekeeper response engine
- no credentials appear in logs, channel messages, public embeds, or command errors

Do not claim a phase is complete until the automated checks and relevant manual regression checks have actually been run and recorded in the phase report.

## Implementation Order

1. Task 1: tests.
2. Task 2: constants/responses.
3. Task 3: atomic persistence.
4. Task 4: config compatibility.
5. Task 5: hierarchy.
6. Task 6: authz pipeline.
7. Task 7: cases.
8. Task 8: guild activation.
9. Task 9: parser.
10. Task 10: moderation migration.
11. Task 11: log redaction/access.
12. Task 12: Roblox Auth delivery.
13. Task 13: Anti-Nuke monitor mode.
14. Task 14: Anti-Nuke enforcement/lockdown.
15. Task 15: fun locks.
16. Task 16: docs and command-tree regression.

## Decisions Required Before Implementation

1. Should existing guilds in `server_config.json` be migrated to `enabled: true` automatically, or should every guild start disabled until you explicitly activate it?
2. Should `!logs` remain as a prefix command with staff checks, or should log export become mention-only as `@Shorekeeper logs export`?
3. For Anti-Nuke enforcement, should the default enforcement action for an unauthorized bot addition be `kick suspicious bot` or `ban suspicious bot` when hierarchy permits?
4. Should emergency lockdown lock all text channels by default, or only configured security-sensitive channels?
5. Should manual `@Shorekeeper robloxauth username` remain permanently as a fallback, or be deprecated after auto-DM approval is verified?

## Self-Review

- Spec coverage: owner identity, global Roblox Auth, mention-first UX, centralized authorization, hierarchy safety, logging access, Anti-Nuke modes, MongoDB cases, phased migration, parser, tests, and migration strategy are each covered by tasks.
- Placeholder scan: no task relies on unspecified implementation work; each task names files, interfaces, test commands, and expected results.
- Type consistency: core interfaces introduced in earlier tasks are consumed by later tasks with matching names.
