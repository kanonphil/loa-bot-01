"""봇 서버(다른 머신)의 /api/internal 호출용 얇은 클라이언트."""
import httpx

from webapp import config


async def is_registered(discord_id: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/verify-user",
            params={"discord_id": discord_id},
            headers={"X-Webapp-Key": config.BOT_API_WEBAPP_KEY},
        )
        resp.raise_for_status()
        return resp.json()["registered"]


async def get_user_characters(discord_id: str) -> list[dict]:
    """AI 상담 프롬프트에 넣을 캐릭터 정보. 실패해도 앱이 죽으면 안 되니 호출 측에서 감싸서 씀."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/user-characters",
            params={"discord_id": discord_id},
            headers={"X-Webapp-Key": config.BOT_API_WEBAPP_KEY},
        )
        resp.raise_for_status()
        return resp.json()
