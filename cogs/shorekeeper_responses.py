import os
import discord
from typing import Union

# Exact Discord emoji IDs for Shorekeeper custom emojis
# Format: <:name:id> or <a:name:id> for animated emojis

# Emoji ID constants (exact values from user instructions)
EMOJI_IDS = {
    "confused": "1551573949484113940",
    "error": "1551573921701167185",
    "moderation": "1551573657740902461",
    "roblox": "1551574489265868840",
    "security": "1551573726955307008",
    "success": "1551573755728502886",
    "verification": "1551573817825173595",
    "warning": "1551573856828002324",
    "love": "1551573778209710100",  # Animated emoji
}

def _get_emoji_id(name: str) -> str:
    """Get emoji ID from the centralized EMOJI_IDS mapping"""
    return EMOJI_IDS.get(name, "")

def _format_emoji(name: str, emoji_id: str, animated: bool = False) -> str:
    """Format emoji string from ID"""
    if emoji_id.isdigit() and len(emoji_id) > 0:
        if animated:
            return f"<a:{name}:{emoji_id}>"
        else:
            return f"<:{name}:{emoji_id}>"
    return ""

# Emoji system with graceful fallback: custom → Unicode → text
class ShorekeeperEmojis:
    # Custom emojis with exact Discord IDs
    # Format: logical name = emoji name (for lookup in EMOJI_IDS)
    _custom_emojis = {
        "success": "success",
        "love": "love",
        "error": "error",
        "warning": "warning",
        "info": "info",
        "loading": "loading",
        "music": "music",
        "verification": "verification",
        "moderation": "moderation",
        "settings": "settings",
        "security": "security",
        "roblox": "roblox",
        "confused": "confused",
        "minecraft": "minecraft",
        "ai": "ai"
    }

    # Unicode fallbacks (matching instructions)
    _unicode_fallbacks = {
        "success": "🍉",   # watermelon
        "love": "💕",     # growing heart
        "error": "😭",    # loudly crying face
        "warning": "👉",   # backhand index pointing right
        "info": "ℹ️",     # information source
        "loading": "⌛",   # hourglass done
        "music": "♪",     # eighth note
        "verification": "💐", # bouquet
        "moderation": "😑", # expressionless face
        "settings": "⟡",   # circled white star
        "security": "😰",  # anxious face with sweat
        "roblox": "📱",    # mobile phone
        "confused": "❓",  # question mark
        "minecraft": "⛏️", # pick
        "ai": "🤖"        # robot
    }

    # Text fallbacks (last resort)
    _text_fallbacks = {
        "success": "success",
        "love": "love",
        "error": "error",
        "warning": "warning",
        "info": "info",
        "loading": "loading",
        "music": "music",
        "verification": "verification",
        "moderation": "moderation",
        "settings": "settings",
        "security": "security",
        "roblox": "roblox",
        "confused": "confused",
        "minecraft": "minecraft",
        "ai": "ai"
    }

    # Bot's emoji cache (set by main.py after emoji upload)
    bot_emoji_cache = None

    @classmethod
    def get(cls, name: str) -> str:
        """Get emoji with graceful fallback: custom → Unicode → text"""
        # Special handling for animated love emoji
        if name == "love":
            emoji_id = _get_emoji_id("love")
            if emoji_id:
                return _format_emoji("love", emoji_id, animated=True)

        # Try bot's emoji cache first
        emoji_name = cls._custom_emojis.get(name, "")
        if emoji_name and cls.bot_emoji_cache:
            emoji_id = cls.bot_emoji_cache.get(emoji_name)
            if emoji_id:
                return f"<:{emoji_name}:{emoji_id}>"

        # Try custom emoji from the centralized EMOJI_IDS mapping
        emoji_id = _get_emoji_id(cls._custom_emojis.get(name, ""))
        custom_emoji = _format_emoji(cls._custom_emojis.get(name, ""), emoji_id)
        if custom_emoji:
            return custom_emoji

        # Fall back to Unicode
        unicode_emoji = cls._unicode_fallbacks.get(name)
        if unicode_emoji:
            return unicode_emoji

        # Last resort: text fallback
        return cls._text_fallbacks.get(name, "")
# Color palette (Shorekeeper inspired)
class ShorekeeperColors:
    SUCCESS = 0x57F287   # Green
    ERROR = 0xED4245     # Red
    WARNING = 0xFEE75C   # Yellow
    INFO = 0x5865F2      # Blue
    PRIMARY = 0x5865F2   # Blue
    SECONDARY = 0x3498DB # Lighter blue
    ACCENT = 0xEB459E    # Pink/Purple
    DARK = 0x2C3E50      # Dark blue
    LIGHT = 0xECF0F1     # Light gray

    @classmethod
    def get_color(cls, kind: str) -> int:
        """Get color for a given kind"""
        color_map = {
            "success": cls.SUCCESS,
            "error": cls.ERROR,
            "warning": cls.WARNING,
            "info": cls.INFO,
            "moderation": cls.SECONDARY,
            "security": cls.ACCENT,
            "music": cls.PRIMARY
        }
        return color_map.get(kind.lower(), cls.INFO)

# Helper functions for Shorekeeper-themed responses
class ShorekeeperResponses:
    @staticmethod
    def get_emoji(name: str) -> str:
        """Get a Shorekeeper emoji with graceful fallback"""
        return ShorekeeperEmojis.get(name)

    @staticmethod
    def get_color(kind: str) -> int:
        """Get a Shorekeeper color for the given kind"""
        return ShorekeeperColors.get_color(kind)

    @staticmethod
    def get_button_label(action: str) -> str:
        """Get Shorekeeper-themed button label"""
        labels = {
            "confirm": "✦ Confirm",
            "cancel": "✕ Cancel",
            "verify": "◇ Verify",
            "play": "⌁ Play",
            "pause": "Ⅱ Pause",
            "resume": "▶ Resume",
            "previous": "◀ Previous",
            "next": "▶ Next",
            "refresh": "⟳ Refresh",
            "settings": "⟡ Settings"
        }
        return labels.get(action.lower(), action.title())

    @staticmethod
    def get_select_placeholder(category: str) -> str:
        """Get Shorekeeper-themed select menu placeholder"""
        placeholders = {
            "moderation": "◇ Select a moderation action",
            "music": "⌁ Select a music option",
            "settings": "⟡ Select a setting",
            "security": "◆ Select a security option",
            "roblox": "🎮 Select a Roblox option",
            "minecraft": "⛏️ Select a Minecraft option"
        }
        return placeholders.get(category.lower(), f"◇ Select {category.title()}")

    @staticmethod
    def create_embed(title: str, description: str = None, kind: str = "info") -> discord.Embed:
        """Create a Shorekeeper-themed embed"""
        emoji_prefix = ShorekeeperEmojis.get(kind.split()[0] if ' ' in kind else kind)
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title

        embed = discord.Embed(
            title=title_text,
            description=description or "",
            color=ShorekeeperColors.get_color(kind)
        )

        # Add Shorekeeper footer
        from cogs.core.responses import response_engine
        embed.set_footer(text=response_engine.footer)
        return embed

    @staticmethod
    async def send_response(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        kind: str = "info",
        ephemeral: bool = False
    ) -> None:
        """Send a Shorekeeper-themed response"""
        embed = ShorekeeperResponses.create_embed(title, description, kind)

        if hasattr(destination, 'response'):  # Interaction
            if destination.response.is_done():
                await destination.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await destination.response.send_message(embed=embed, ephemeral=ephemeral)
        else:  # Messageable (channel, user, etc.)
            await destination.send(embed=embed)

    @staticmethod
    async def send_success(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        ephemeral: bool = False
    ) -> None:
        """Send a success response"""
        await ShorekeeperResponses.send_response(destination, title, description, "success", ephemeral)

    @staticmethod
    async def send_error(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        ephemeral: bool = False
    ) -> None:
        """Send an error response"""
        await ShorekeeperResponses.send_response(destination, title, description, "error", ephemeral)

    @staticmethod
    async def send_warning(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        ephemeral: bool = False
    ) -> None:
        """Send a warning response"""
        await ShorekeeperResponses.send_response(destination, title, description, "warning", ephemeral)

    @staticmethod
    async def send_info(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        ephemeral: bool = False
    ) -> None:
        """Send an info response"""
        await ShorekeeperResponses.send_response(destination, title, description, "info", ephemeral)

    @staticmethod
    async def send_loading(
        destination: Union[discord.Interaction, discord.abc.Messageable],
        title: str,
        description: str = None,
        ephemeral: bool = False
    ) -> None:
        """Send a loading response"""
        await ShorekeeperResponses.send_response(destination, title, description, "loading", ephemeral)

# Global instance for easy access
shorekeeper = ShorekeeperResponses()