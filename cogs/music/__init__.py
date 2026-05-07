from .player import Music
from .setup import MusicSetup


async def setup(bot):
    await bot.add_cog(Music(bot))
    await bot.add_cog(MusicSetup(bot))
