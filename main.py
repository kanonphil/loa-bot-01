import asyncio

import config
from config import DISCORD_TOKEN
from bot.bot import LoABot


async def main() -> None:
    async with LoABot() as bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    # ADMIN_API_KEY / WEBAPP_API_KEY가 빠진 채로 뜨지 않도록 기동 전에 확인
    config.validate_required_settings()
    asyncio.run(main())
