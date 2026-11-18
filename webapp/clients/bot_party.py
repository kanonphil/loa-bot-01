"""공대 화면 전용 봇 호출 — 공용 bot_client에 없는 것만 여기 둔다."""
from webapp import config
from webapp.clients.bot_client import _get_client, _headers


async def get_raid_check_summary(discord_id: str) -> dict:
    """내 캐릭터(레벨·직업·서포터 여부) + 이번 주 완료 + 익스트림 원정대 상태를 한 번에.
    공대 목록/개설 화면이 "어느 캐릭터가 들어갈 수 있나"를 계산하는 재료."""
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/raid-check-summary",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
