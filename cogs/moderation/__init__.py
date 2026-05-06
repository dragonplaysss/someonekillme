from .moderation_core import ModerationCore
from .moderation_panel import ModerationPanel


async def setup(bot):
    print("Loading moderation package")
    await bot.add_cog(ModerationCore(bot))
    await bot.add_cog(ModerationPanel(bot))
    print("Moderation package loaded")
