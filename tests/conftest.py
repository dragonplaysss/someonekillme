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


@dataclass(order=False)
class FakeRole:
    position: int
    id: int = field(compare=False)
    name: str = field(compare=False, default="role")
    managed: bool = field(compare=False, default=False)

    @property
    def mention(self):
        return f"<@&{self.id}>"

    def unicode_emoji(self):
        return None

    def is_default(self):
        return False

    def is_bot_managed(self):
        return self.managed

    def position_relative_to(self, other):
        # doc-like convenience helper; returns -1/0/1 like discord.py helpers
        if self < other:
            return -1
        if self > other:
            return 1
        return 0

    def __eq__(self, other):
        if not isinstance(other, (FakeRole, Role)):
            return NotImplemented
        if isinstance(other, FakeRole):
            return self.position == other.position
        return self.position == other.position

    def __ne__(self, other):
        if not isinstance(other, (FakeRole, Role)):
            return NotImplemented
        if isinstance(other, FakeRole):
            return self.position != other.position
        return self.position != other.position

    def __lt__(self, other):
        if isinstance(other, (FakeRole, Role)):
            if isinstance(other, FakeRole):
                return self.position < other.position
            return self.position < other.position
        if isinstance(other, (int, float)):
            return self.position < other
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, (FakeRole, Role)):
            if isinstance(other, FakeRole):
                return self.position <= other.position
            return self.position <= other.position
        if isinstance(other, (int, float)):
            return self.position <= other
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, (FakeRole, Role)):
            if isinstance(other, FakeRole):
                return self.position > other.position
            return self.position > other.position
        if isinstance(other, (int, float)):
            return self.position > other
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, (FakeRole, Role)):
            if isinstance(other, FakeRole):
                return self.position >= other.position
            return self.position >= other.position
        if isinstance(other, (int, float)):
            return self.position >= other
        return NotImplemented


@dataclass
class Role:
    position: int
    id: int
    name: str = "role"
    managed: bool = False

    def __eq__(self, other):
        if not isinstance(other, (Role, FakeRole)):
            return NotImplemented
        if isinstance(other, Role):
            return self.position == other.position
        return self.position == other.position

    def __ne__(self, other):
        if not isinstance(other, (Role, FakeRole)):
            return NotImplemented
        if isinstance(other, Role):
            return self.position != other.position
        return self.position != other.position

    def __lt__(self, other):
        if isinstance(other, (Role, FakeRole)):
            if isinstance(other, Role):
                return self.position < other.position
            return self.position < other.position
        if isinstance(other, (int, float)):
            return self.position < other
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, (Role, FakeRole)):
            if isinstance(other, Role):
                return self.position <= other.position
            return self.position <= other.position
        if isinstance(other, (int, float)):
            return self.position <= other
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, (Role, FakeRole)):
            if isinstance(other, Role):
                return self.position > other.position
            return self.position > other.position
        if isinstance(other, (int, float)):
            return self.position > other
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, (Role, FakeRole)):
            if isinstance(other, Role):
                return self.position >= other.position
            return self.position >= other.position
        if isinstance(other, (int, float)):
            return self.position >= other
        return NotImplemented
