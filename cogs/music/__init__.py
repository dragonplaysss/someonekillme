import os

from .setup import MusicSetup


async def setup(bot):
    await bot.add_cog(MusicSetup(bot))

    backend = os.getenv("MUSIC_BACKEND", "ytdlp").lower()
    if backend == "wavelink":
        from . import wavelink_player as wl

        if wl.wavelink is None:
            print(
                "[MUSIC] MUSIC_BACKEND=wavelink but wavelink is not installed; "
                "using yt-dlp backend."
            )
            from .player import Music

            await bot.add_cog(Music(bot))
            return

        from .wavelink_player import WavelinkMusic

        await bot.add_cog(WavelinkMusic(bot))
    else:
        from .player import Music

        await bot.add_cog(Music(bot))
