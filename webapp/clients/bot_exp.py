"""원정대·더보기 화면이 새로 쓰는 봇 내부 API (로스트아크 공용 데이터 · 전투력 기록).

봇 쪽 엔드포인트가 아직 없거나(404) 응답이 늦어도 화면이 깨지면 안 되므로, 여기 함수는 예외를
던지지 않고 실패하면 None을 돌려준다. 호출하는 화면은 None을 "표시 못 함" 상태로 그린다.
"""
import logging

from webapp import config
from webapp.clients.bot_client import _get_client, _headers

log = logging.getLogger(__name__)

_BASE = "/api/internal"


async def _get(path: str, params: dict, timeout: float = 8) -> dict | None:
    try:
        resp = await _get_client().get(
            f"{config.BOT_API_BASE_URL}{_BASE}{path}", params=params, headers=_headers(), timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — 404·타임아웃·잘못된 JSON 모두 "없음"으로
        log.info("봇 %s 호출 실패: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


async def get_loa_overview(discord_id: str) -> dict | None:
    """공용 로스트아크 개요. 설정 화면은 gold_island_subscribed(내 구독 여부)만 쓴다."""
    return await _get("/loa/overview", {"discord_id": discord_id})


async def set_gold_island_subscription(discord_id: str, enabled: bool) -> dict:
    """골드섬 10분 전 DM 구독 켜기/끄기. 실패하면 {"success": False, "reason": ...}."""
    try:
        resp = await _get_client().post(
            f"{config.BOT_API_BASE_URL}{_BASE}/loa/gold-island-subscription",
            json={"discord_id": discord_id, "enabled": enabled},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 404:
            return {"success": False, "reason": "봇 서버가 아직 이 기능을 지원하지 않습니다."}
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.info("골드섬 구독 변경 실패: %s", exc)
        return {"success": False, "reason": "봇 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요."}
    return data if isinstance(data, dict) else {"success": False}


async def get_loa_prices() -> dict | None:
    """시세 추적 아이템. {"available", "fetched_at", "items": [...]} 또는 None."""
    return await _get("/loa/prices", {})


async def get_character_history(discord_id: str, character_name: str, days: int = 90) -> list[dict] | None:
    """전투력·아이템 레벨 일별 기록. 오래된 날짜 → 최신 순으로 정렬해 돌려준다."""
    from webapp.clients.bot_client import _q

    data = await _get(f"/characters/{_q(character_name)}/history", {"discord_id": discord_id, "days": days})
    if data is None:
        return None
    items = [i for i in (data.get("items") or []) if isinstance(i, dict) and i.get("date")]
    return sorted(items, key=lambda i: str(i["date"]))
