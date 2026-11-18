"""홈 화면 전용 봇 호출 — 숙제표 요약과 로스트아크 공용 데이터(점검·오늘의 콘텐츠·시세·이벤트).

로아 데이터 엔드포인트는 봇 쪽에 아직 없을 수 있다(404)·느릴 수 있다(타임아웃)·점검 중일 수 있다.
홈이 그것 때문에 깨지면 안 되므로 로아 데이터 호출은 예외를 던지지 않고 `available: False`를 돌려준다.
"""
import logging

import httpx

from webapp import config
from webapp.clients.bot_client import _get_client, _headers  # 같은 연결·헤더 재사용

logger = logging.getLogger("webapp")

_LOA_TIMEOUT = 5  # 홈 렌더를 오래 붙잡지 않도록 일반 호출(10초)보다 짧게


def _base() -> str:
    return f"{config.BOT_API_BASE_URL}/api/internal"


async def get_raid_check_summary(discord_id: str) -> dict:
    """숙제표 한 화면에 필요한 데이터 전부(캐릭터별 완료·표시 레이드·익스트림·골드)."""
    resp = await _get_client().get(
        f"{_base()}/raid-check-summary", params={"discord_id": discord_id}, headers=_headers(), timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _unavailable(reason: str | None = None) -> dict:
    return {"available": False, "reason": reason}


async def _loa_get(path: str, params: dict | None = None) -> dict:
    try:
        resp = await _get_client().get(f"{_base()}{path}", params=params, headers=_headers(), timeout=_LOA_TIMEOUT)
        if resp.status_code != 200:
            return _unavailable()
        data = resp.json()
        return data if isinstance(data, dict) else _unavailable()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("로아 데이터 호출 실패 %s: %r", path, exc)
        return _unavailable()


async def get_loa_overview(discord_id: str) -> dict:
    """점검 공지·진행 중 이벤트·오늘의 콘텐츠·골드섬 알림 구독 여부."""
    return await _loa_get("/loa/overview", {"discord_id": discord_id})


async def get_loa_prices() -> dict:
    """추적 중인 아이템 시세(관리자가 정한 목록 — 비어 있으면 카드를 안 그린다)."""
    return await _loa_get("/loa/prices")


async def set_gold_island_subscription(discord_id: str, enabled: bool) -> dict:
    resp = await _get_client().post(
        f"{_base()}/loa/gold-island-subscription",
        json={"discord_id": discord_id, "enabled": enabled},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
