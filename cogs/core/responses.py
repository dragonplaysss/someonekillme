import discord
from datetime import datetime

from cogs.core.constants import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SECURITY,
    COLOR_SUCCESS,
    COLOR_WARNING,
)
from cogs.shorekeeper_responses import ShorekeeperEmojis


class ShorekeeperUI:
    def __init__(self):
        from cogs.shorekeeper_responses import ShorekeeperEmojis
        self.ShorekeeperEmojis = ShorekeeperEmojis
        pass

    @property
    def footer(self) -> str:
        """Dynamic footer showing current time"""
        return f"Shorekeeper • Today at {datetime.now().strftime('%H:%M')}"

    def build(self, title: str, description: str, *, color: int,
              target_user=None, moderator_user=None, action=None,
              duration=None, reason=None, case_id=None,
              event_text=None, account=None) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow(),
        )

        # Add fields for structured responses if provided
        if any(param is not None for param in [target_user, moderator_user, action, duration, reason, case_id, event_text, account]):
            # Add a separator field for visual separation
            embed.add_field(name="​", value="‎", inline=False)

            if event_text is not None:
                embed.add_field(name="​", value=f"Event\n{event_text}", inline=True)

            if target_user is not None:
                target_str = f"@{target_user.name}" if hasattr(target_user, 'name') else str(target_user)
                embed.add_field(name="​", value=f"Target\n{target_str}", inline=True)

            if moderator_user is not None:
                moderator_str = f"@{moderator_user.name}" if hasattr(moderator_user, 'name') else str(moderator_user)
                embed.add_field(name="​", value=f"Moderator\n{moderator_str}", inline=True)

            if action is not None:
                embed.add_field(name="​", value=f"Action\n{action}", inline=True)

            if duration is not None:
                embed.add_field(name="​", value=f"Duration\n{duration}", inline=True)

            if reason is not None:
                embed.add_field(name="​", value=f"Reason\n{reason}", inline=True)

            if case_id is not None:
                embed.add_field(name="​", value=f"Case\n#{case_id}", inline=True)

            if account is not None:
                embed.add_field(name="​", value=f"Account\n{account}", inline=True)

        embed.set_footer(text=self.footer)
        return embed

    def success(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("success")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_SUCCESS)

    def failure(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("error")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_ERROR)

    def warning(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("warning")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_WARNING)

    def permission_denied(self, detail: str) -> discord.Embed:
        return self.failure(
            "Permission Denied",
            f"{detail} Shorekeeper will not move without clear authority.",
        )

    def hierarchy_denied(self, detail: str) -> discord.Embed:
        return self.failure(
            "Hierarchy Protected",
            f"{detail} Discord's role order is absolute.",
        )

    def moderation_result(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("moderation")
        title_text = f"{emoji_prefix} MEMBER SANCTIONED" if emoji_prefix else "MEMBER SANCTIONED"
        return self.build(title_text, description, color=COLOR_SECURITY)

    def case_result(self, case_id: int, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("info")
        title_text = f"{emoji_prefix} Case #{case_id}" if emoji_prefix else f"Case #{case_id}"
        return self.build(title_text, description, color=COLOR_INFO)

    def anti_nuke_alert(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("security")
        title_text = f"{emoji_prefix} SECURITY INTERVENTION" if emoji_prefix else "SECURITY INTERVENTION"
        return self.build(title_text, description, color=COLOR_SECURITY)

    def lockdown(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("security")
        title_text = f"{emoji_prefix} SECURITY INTERVENTION" if emoji_prefix else "SECURITY INTERVENTION"
        return self.build(title_text, description, color=COLOR_SECURITY)

    def roblox_auth_approval(self, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("roblox")
        title_text = f"{emoji_prefix} Roblox Auth Approved" if emoji_prefix else "Roblox Auth Approved"
        embed = self.build(title_text, description, color=COLOR_SUCCESS,
                          target_user=None, moderator_user=None, action=None,
                          duration=None, reason=None, case_id=None, event_text=None, account=None)
        # Add medium Roblox emoji as decorative badge at the bottom
        roblox_emoji = self.ShorekeeperEmojis.get("roblox")
        embed.add_field(name="​", value=roblox_emoji, inline=False)
        return embed

    def roblox_auth_delivery(self, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("roblox")
        title_text = f"{emoji_prefix} Roblox Auth Delivered" if emoji_prefix else "Roblox Auth Delivered"
        embed = self.build(title_text, description, color=COLOR_SUCCESS,
                          target_user=None, moderator_user=None, action=None,
                          duration=None, reason=None, case_id=None, event_text=None, account=None)
        # Add medium Roblox emoji as decorative badge at the bottom
        roblox_emoji = self.ShorekeeperEmojis.get("roblox")
        embed.add_field(name="​", value=roblox_emoji, inline=False)
        return embed

    def dm_failure(self, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("error")
        title_text = f"{emoji_prefix} DM Delivery Failed" if emoji_prefix else "DM Delivery Failed"
        return self.build(title_text, description, color=COLOR_WARNING)

    def configuration(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("settings")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_INFO)

    def help(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("info")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_INFO)

    def verification(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("verification")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_INFO)

    def snipe(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("roblox")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_SUCCESS)

    def music(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("music")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_INFO)

    def settings(self, title: str, description: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("settings")
        title_text = f"{emoji_prefix} {title}" if emoji_prefix else title
        return self.build(title_text, description, color=COLOR_INFO)

    def parser_error(self, detail: str) -> discord.Embed:
        emoji_prefix = self.ShorekeeperEmojis.get("error")
        title_text = f"{emoji_prefix} Command Not Understood" if emoji_prefix else "Command Not Understood"
        return self.build(title_text, detail, color=COLOR_WARNING)

    # Structured response methods for specific use cases

    def moderation_action(self, target_user=None, moderator_user=None, action: str = None,
                          duration: str = None, reason: str = None, case_id: int = None) -> discord.Embed:
        """Create a structured moderation action response"""
        emoji_prefix = self.ShorekeeperEmojis.get("moderation")
        title = f"{emoji_prefix} MEMBER SANCTIONED" if emoji_prefix else "MEMBER SANCTIONED"
        description = "The requested moderation action has been completed."
        return self.build(
            title, description, color=COLOR_SECURITY,
            target_user=target_user, moderator_user=moderator_user,
            action=action, duration=duration, reason=reason, case_id=case_id
        )

    def security_intervention(self, event: str = None, actor=None, action: str = None,
                              case_id: int = None) -> discord.Embed:
        """Create a structured security/intervention response"""
        emoji_prefix = self.ShorekeeperEmojis.get("security")
        title = f"{emoji_prefix} SECURITY INTERVENTION" if emoji_prefix else "SECURITY INTERVENTION"
        description = "Suspicious activity was detected and protective measures have been activated."
        return self.build(
            title, description, color=COLOR_SECURITY,
            target_user=actor,  # Actor
            action=action,      # Action
            case_id=case_id,    # Case
            event_text=event    # Event
        )

    def roblox_auth_response(self, account: str = None, requester=None,
                             approval: str = None, expires: str = None) -> discord.Embed:
        """Create a structured Roblox Auth response"""
        emoji_prefix = self.ShorekeeperEmojis.get("roblox")
        title = f"{emoji_prefix} Authentication Ready" if emoji_prefix else "Authentication Ready"
        description = "Your approved Roblox account is ready."
        embed = self.build(
            title, description, color=COLOR_SUCCESS,
            target_user=requester,  # Requester
            action=approval,        # Approval
            duration=expires,       # Expires
            account=account         # Account
        )
        # Add medium Roblox emoji as decorative badge at the bottom
        roblox_emoji = self.ShorekeeperEmojis.get("roblox")
        embed.add_field(name="​", value=roblox_emoji, inline=False)
        return embed

    def roblox_snipe_response(self, account: str = None, status: str = None,
                              game: str = None, server: str = None,
                              time_left: str = None, error: str = None) -> discord.Embed:
        """Create a structured Roblox Snipe response - never exposes raw exceptions"""
        if error:
            # Handle error case gracefully
            emoji_prefix = self.ShorekeeperEmojis.get("error")
            title = f"{emoji_prefix} Snipe Failed" if emoji_prefix else "Snipe Failed"
            description = f"An error occurred during the snipe operation: {str(error)[:100]}"
            return self.build(title, description, color=COLOR_ERROR)

        emoji_prefix = self.ShorekeeperEmojis.get("roblox")
        title = f"{emoji_prefix} Snipe Result" if emoji_prefix else "Snipe Result"

        # Build description with available info, using "Unknown" for missing values
        desc_parts = []
        if account:
            desc_parts.append(f"Account: {account}")
        else:
            desc_parts.append("Account: Unknown")

        if status:
            desc_parts.append(f"Status: {status}")
        else:
            desc_parts.append("Status: Unknown")

        if game:
            desc_parts.append(f"Game: {game}")
        else:
            desc_parts.append("Game: Unknown")

        if server:
            desc_parts.append(f"Server: {server}")
        else:
            desc_parts.append("Server: Unknown")

        if time_left:
            desc_parts.append(f"Time Left: {time_left}")
        else:
            desc_parts.append("Time Left: Unknown")

        description = "\n".join(desc_parts)
        return self.build(title, description, color=COLOR_SUCCESS)

    def verification_response(self, title: str, description: str) -> discord.Embed:
        """Create a structured verification response"""
        emoji_prefix = self.ShorekeeperEmojis.get("verification")
        title_text = f"{emoji_prefix} VERIFICATION COMPLETE" if emoji_prefix else "VERIFICATION COMPLETE"
        return self.build(title_text, description, color=COLOR_INFO)

    def music_response(self, title: str, description: str) -> discord.Embed:
        """Create a structured music response"""
        emoji_prefix = self.ShorekeeperEmojis.get("music")
        title_text = f"{emoji_prefix} MUSIC PLAYING" if emoji_prefix else "MUSIC PLAYING"
        return self.build(title_text, description, color=COLOR_INFO)

    def settings_response(self, title: str, description: str) -> discord.Embed:
        """Create a structured settings response"""
        emoji_prefix = self.ShorekeeperEmojis.get("settings")
        title_text = f"{emoji_prefix} SETTINGS UPDATED" if emoji_prefix else "SETTINGS UPDATED"
        return self.build(title_text, description, color=COLOR_INFO)

    def help_response(self, title: str, description: str) -> discord.Embed:
        """Create a structured help response"""
        emoji_prefix = self.ShorekeeperEmojis.get("info")
        title_text = f"{emoji_prefix} SHOREKEEPER HELP" if emoji_prefix else "SHOREKEEPER HELP"
        return self.build(title_text, description, color=COLOR_INFO)


# Global instance for backward compatibility
response_engine = ShorekeeperUI()