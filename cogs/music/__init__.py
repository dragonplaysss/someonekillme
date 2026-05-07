import os


async def setup(bot):
    from .setup import MusicSetup

    await bot.add_cog(MusicSetup(bot))

    if os.getenv("MUSIC_BACKEND", "wavelink").lower() == "wavelink":
        from .wavelink_player import WavelinkMusic

        await bot.add_cog(WavelinkMusic(bot))
    else:
        from .player import Music

        await bot.add_cog(Music(bot))
