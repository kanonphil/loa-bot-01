import asyncio
from config import DISCORD_TOKEN
from bot.bot import LoABot


async def main() -> None:
    async with LoABot() as bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
