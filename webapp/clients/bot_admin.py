"""관리자 화면 전용 봇 호출 — 2단계에서 새로 생긴 엔드포인트(작업 기록·유저 영향 범위·시세 아이템·
난이도 클리어 골드)만 모은다. 기존 admin_* 호출은 bot_client에 그대로 있다.

새 엔드포인트는 봇 서버가 아직 배포 전일 수 있으니(404/연결 실패) 조회 함수는 예외 대신 None을 돌려주고,
화면이 "아직 쓸 수 없음" 안내로 대체한다 — 새 기능 하나 때문에 관리 화면 전체가 죽으면 안 된다."""
import logging

import httpx

from webapp import config
from webapp.clients import bot_client
from webapp.clients.bot_client import _admin_post, _cached_get, _get_client, _headers, _q

log = logging.getLogger(__name__)


async def get_status(discord_id: str) -> dict | None:
    """관리 화면 머리줄의 봇 상태 칩 — 짧게 캐시(모든 탭이 매번 부른다). 실패하면 None."""
    try:
        return await _cached_get(
            f"admin_status:{discord_id}",
            f"{config.BOT_API_BASE_URL}/api/internal/admin/status?discord_id={_q(discord_id)}",
        )
    except Exception:
        return None


async def _get_optional(path: str, discord_id: str, **params) -> dict | None:
    """새 엔드포인트 조회 — 없거나(404) 실패하면 None."""
    try:
        resp = await _get_client().get(
            f"{config.BOT_API_BASE_URL}/api/internal/{path}",
            params={"discord_id": discord_id, **{k: v for k, v in params.items() if v is not None}},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None
    except Exception:  # respx 목킹 누락 등 — 보조 데이터라 화면은 계속 그린다
        log.debug("optional bot call failed: %s", path, exc_info=True)
        return None


async def _post_optional(path: str, discord_id: str, timeout: int = 15, **body) -> dict:
    """새 POST — 서버가 이 기능을 모르면(404) 사유가 있는 실패로 돌려준다."""
    try:
        resp = await _get_client().post(
            f"{config.BOT_API_BASE_URL}/api/internal/{path}",
            json={"discord_id": discord_id, **body},
            headers=_headers(),
            timeout=timeout,
        )
    except httpx.HTTPError:
        return {"success": False, "reason": "봇 서버에 연결하지 못했습니다."}
    if resp.status_code == 404:
        return {"success": False, "reason": "봇 서버가 아직 이 기능을 지원하지 않습니다."}
    try:
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return {"success": False, "reason": "처리하지 못했습니다. 잠시 후 다시 시도해주세요."}


# ── 난이도 — 클리어 골드가 늘었다(계약 §2) ─────────────────────────

async def add_difficulty(
    discord_id: str, raid_name: str, difficulty: str, min_level: int,
    total_slots: int, party_split: int | None, gates: int, clear_gold: int | None,
) -> dict:
    return await _admin_post(
        "difficulties/add", discord_id, raid_name=raid_name, difficulty=difficulty,
        min_level=min_level, total_slots=total_slots, party_split=party_split, gates=gates,
        clear_gold=clear_gold,
    )


async def update_difficulty(
    discord_id: str, raid_name: str, difficulty: str, min_level: int,
    total_slots: int, party_split: int | None, gates: int, clear_gold: int | None,
) -> dict:
    return await _admin_post(
        "difficulties/update", discord_id, raid_name=raid_name, difficulty=difficulty,
        min_level=min_level, total_slots=total_slots, party_split=party_split, gates=gates,
        clear_gold=clear_gold,
    )


async def raid_references(discord_id: str, name: str, difficulty: str | None = None) -> dict | None:
    """이름 변경·삭제 판단용 참조 건수 — 실패해도 편집 화면은 그려야 하므로 None 허용."""
    try:
        return await bot_client.admin_raid_references(discord_id, name, difficulty)
    except Exception:
        return None


# ── 작업 기록(계약 §4) ─────────────────────────────────────────

async def list_actions(discord_id: str, kind: str = "all", limit: int = 100) -> dict | None:
    return await _get_optional("admin/actions", discord_id, kind=kind, limit=limit)


async def undo_action(discord_id: str, action_id: int | str) -> dict:
    return await _post_optional(f"admin/actions/{_q(action_id)}/undo", discord_id)


# ── 유저 내보내기 영향 범위(계약 §5) ────────────────────────────

async def user_impact(discord_id: str, target_discord_id: str) -> dict | None:
    return await _get_optional(f"admin/users/{_q(target_discord_id)}/impact", discord_id)


# ── 시세로 볼 아이템(계약 §1) ───────────────────────────────────

async def get_tracked_items(discord_id: str) -> dict | None:
    return await _get_optional("admin/loa/tracked-items", discord_id)


async def set_tracked_items(discord_id: str, names: list[str]) -> dict:
    return await _post_optional("admin/loa/tracked-items", discord_id, names=names)


# ── 전체 공지 진행 상황 ─────────────────────────────────────────

async def broadcast_status(discord_id: str) -> dict:
    """진행 중이 아니거나 조회에 실패하면 빈 dict."""
    return await _get_optional("admin/notify-all/status", discord_id) or {}
