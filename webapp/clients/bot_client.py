"""봇 서버(다른 머신)의 /api/internal 호출용 얇은 클라이언트."""
import time

import httpx

from webapp import config


def _headers() -> dict:
    return {"X-Webapp-Key": config.BOT_API_WEBAPP_KEY}


# 봇 서버는 다른 머신이라, 함수마다 새 httpx.AsyncClient()를 열면 내부 API 호출마다
# 매번 새 TCP 연결을 맺어야 했다 — 프로세스 생애주기 동안 하나만 만들어 재사용
# (keep-alive)한다. webapp/main.py의 lifespan이 종료 시 aclose()로 정리한다.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient()
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# 레이드/카테고리/서포터직업은 관리자가 봇 명령으로 수정할 때만 바뀌는 정적에 가까운
# 데이터인데, 페이지 조회는 물론 레이드체크 토글처럼 자주 눌리는 액션에서도 매번
# 봇 서버를 왕복하고 있었다 — 짧은 TTL 캐시로 왕복 횟수를 크게 줄인다.
# (테스트는 webapp/tests/conftest.py의 autouse 픽스처가 매 테스트 전에 이 캐시를 비운다.)
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, object]] = {}


async def _cached_get(cache_key: str, url: str) -> object:
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    resp = await _get_client().get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    value = resp.json()
    _cache[cache_key] = (now, value)
    return value


def _invalidate_raid_cache() -> None:
    """관리자가 카테고리/레이드/난이도/직업을 바꾼 직후 호출 — 안 하면 최대 60초간
    (레이드체크·공대개설 등 사이트 전체가) 바뀌기 전 데이터를 계속 보게 된다."""
    for key in ("raids", "raid_categories", "support_classes"):
        _cache.pop(key, None)


async def is_registered(discord_id: str) -> bool:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/verify-user",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["registered"]


async def get_guild_info(guild_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/guild-info",
        params={"guild_id": guild_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_user_characters(discord_id: str) -> list[dict]:
    """대시보드/공대/레이드체크/원정대가 공유하는 캐릭터 정보. 실패해도 앱이 죽으면 안 되니 호출 측에서 감싸서 씀."""
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/user-characters",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_user_characters_grouped(discord_id: str) -> list[dict]:
    """원정대 관리 페이지용 — 캐릭터 목록 + 소속 계정 라벨(account_label)."""
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/user-characters-grouped",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_raids() -> dict:
    return await _cached_get("raids", f"{config.BOT_API_BASE_URL}/api/internal/raids")


async def get_raid_categories() -> list[dict]:
    return await _cached_get(
        "raid_categories", f"{config.BOT_API_BASE_URL}/api/internal/raid-categories"
    )


async def get_user_party_history(discord_id: str, limit: int = 20, offset: int = 0) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/user-party-history",
        params={"discord_id": discord_id, "limit": limit, "offset": offset},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_raid_progress(discord_id: str) -> dict:
    """원정대 전체의 이번 주 진행률 — 봇이 한 번에 계산해서 준다.
    예전엔 캐릭터마다 completions/raid-selection을 따로 불러 왕복이 N배였다."""
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/raid-progress",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_support_classes() -> list[str]:
    return await _cached_get(
        "support_classes", f"{config.BOT_API_BASE_URL}/api/internal/support-classes"
    )


async def get_completions(discord_id: str, character_name: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/completions",
        params={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_armory_detail(discord_id: str, character_name: str) -> dict:
    """캐시된 캐릭터 상세를 그대로 받아온다 — 로스트아크 API를 호출하지 않는다.
    최신 정보가 필요하면 sync_armory_detail(동기화 버튼)을 따로 호출해야 한다."""
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/armory-detail",
        params={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


async def sync_armory_detail(discord_id: str, character_name: str) -> dict:
    """"동기화" 버튼 전용 — 실제로 로스트아크 API를 호출해 최신 정보로 갱신한다."""
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/armory-detail/sync",
        params={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


async def get_ranking(metric: str, limit: int = 100, role: str | None = None) -> dict:
    params = {"metric": metric, "limit": limit}
    if role:
        params["role"] = role
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/ranking",
        params=params,
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_raid_selection(discord_id: str, character_name: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/raid-selection",
        params={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def set_raid_selection(discord_id: str, character_name: str, raid_names: list[str]) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/raid-selection",
        json={"discord_id": discord_id, "character_name": character_name, "raid_names": raid_names},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def add_character(discord_id: str, character_name: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/characters/add",
        json={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def remove_character(discord_id: str, character_name: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/characters/remove",
        json={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def sync_characters(discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/characters/sync",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


async def add_account(discord_id: str, api_key: str, character_name: str) -> dict:
    """부계정(로스트아크 API 키) 추가 — 검증(+길드 확인) 후 원정대 캐릭터 전체를 등록한다."""
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/accounts/add",
        json={"discord_id": discord_id, "api_key": api_key, "character_name": character_name},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def list_accounts(discord_id: str) -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/accounts/list",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def remove_account(discord_id: str, key_id: int) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/accounts/remove",
        json={"discord_id": discord_id, "key_id": key_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def toggle_completion(
    discord_id: str, character_name: str, raid_name: str, difficulty: str
) -> bool:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/completions/toggle",
        json={
            "discord_id": discord_id,
            "character_name": character_name,
            "raid_name": raid_name,
            "difficulty": difficulty,
        },
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["completed"]


# ── 공대 모집 ─────────────────────────────────────────────

async def list_parties(guild_id: str) -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties",
        params={"guild_id": guild_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_calendar_parties(guild_id: str, start: str, end: str) -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/calendar",
        params={"guild_id": guild_id, "start": start, "end": end},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_party(message_id: str) -> dict | None:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_party_eligibility(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/eligibility",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def join_party(
    message_id: str,
    discord_id: str,
    character_name: str,
    role: str,
    party_group: int | None = None,
) -> dict:
    payload = {"discord_id": discord_id, "character_name": character_name, "role": role}
    if party_group is not None:
        payload["party_group"] = party_group
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/join",
        json=payload,
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def leave_party(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/leave",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_waitlist_status(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/waitlist-status",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def toggle_waitlist(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/waitlist",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_invitable_users(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/invitable-users",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def create_invite(message_id: str, discord_id: str, target_discord_id: str, slot_number: int) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/invite",
        json={"discord_id": discord_id, "target_discord_id": target_discord_id, "slot_number": slot_number},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_my_invites(discord_id: str) -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/my-invites",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def accept_invite(message_id: str, discord_id: str, character_name: str, role: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/invites/{message_id}/accept",
        json={"discord_id": discord_id, "character_name": character_name, "role": role},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def decline_invite(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/invites/{message_id}/decline",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_party_comments(message_id: str) -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/comments",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def post_party_comment(message_id: str, discord_id: str, display_name: str, avatar_url: str, content: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/comments",
        json={"discord_id": discord_id, "display_name": display_name, "avatar_url": avatar_url, "content": content},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_switch_eligibility(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/switch-eligibility",
        params={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def switch_character(message_id: str, discord_id: str, character_name: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/switch-character",
        json={"discord_id": discord_id, "character_name": character_name},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def switch_role(message_id: str, discord_id: str, new_role: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/switch-role",
        json={"discord_id": discord_id, "new_role": new_role},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_proficiency_options() -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/proficiency-options",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def create_party(
    discord_id: str,
    guild_id: str,
    raid_name: str,
    difficulty: str,
    proficiency: str,
    scheduled_datetime: str,
    memo: str | None,
) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/create",
        json={
            "discord_id": discord_id,
            "guild_id": guild_id,
            "raid_name": raid_name,
            "difficulty": difficulty,
            "proficiency": proficiency,
            "scheduled_datetime": scheduled_datetime,
            "memo": memo,
        },
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ── 파티장 관리 ───────────────────────────────────────────

async def close_party(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/close",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def reopen_party(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/reopen",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def clear_party(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/clear",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def cancel_party(message_id: str, discord_id: str, reason: str | None) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/cancel",
        json={"discord_id": discord_id, "reason": reason},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def kick_member(message_id: str, discord_id: str, target_discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/kick",
        json={"discord_id": discord_id, "target_discord_id": target_discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def reschedule_party(
    message_id: str, discord_id: str, scheduled_datetime: str, memo: str | None
) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/reschedule",
        json={"discord_id": discord_id, "scheduled_datetime": scheduled_datetime, "memo": memo},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def transfer_leader(message_id: str, discord_id: str, new_leader_discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/transfer-leader",
        json={"discord_id": discord_id, "new_leader_discord_id": new_leader_discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── 관리자 (카테고리/레이드/난이도/직업 CRUD) ─────────────────
# 실행 권한 검증은 discord_id를 실어 보내는 봇 서버 쪽에서 다시 한다(admin.py 내부의
# _require_admin) — 여기는 그냥 요청을 전달하고, 성공한 쓰기 요청 뒤에는 반드시
# _invalidate_raid_cache()로 60초 TTL 캐시를 비워 관리자 화면이 바로 최신 상태를 본다.

async def get_job_classes() -> list[dict]:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/job-classes",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def _admin_post(path: str, discord_id: str, **extra) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/admin/{path}",
        json={"discord_id": discord_id, **extra},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        _invalidate_raid_cache()
    return result


async def admin_add_category(discord_id: str, name: str, sort_order: int) -> dict:
    return await _admin_post("categories/add", discord_id, name=name, sort_order=sort_order)


async def admin_delete_category(discord_id: str, name: str) -> dict:
    return await _admin_post("categories/delete", discord_id, name=name)


async def admin_set_category_extreme(discord_id: str, name: str, is_extreme: bool) -> dict:
    return await _admin_post("categories/extreme", discord_id, name=name, is_extreme=is_extreme)


async def admin_add_raid(discord_id: str, name: str, short_name: str, icon: str, category: str) -> dict:
    return await _admin_post(
        "raids/add", discord_id, name=name, short_name=short_name, icon=icon, category=category
    )


async def admin_delete_raid(discord_id: str, name: str) -> dict:
    return await _admin_post("raids/delete", discord_id, name=name)


async def admin_set_raid_active(discord_id: str, name: str, is_active: bool) -> dict:
    return await _admin_post("raids/active", discord_id, name=name, is_active=is_active)


async def admin_set_raid_pinned(discord_id: str, name: str, is_pinned: bool) -> dict:
    return await _admin_post("raids/pin", discord_id, name=name, is_pinned=is_pinned)


async def admin_add_difficulty(
    discord_id: str, raid_name: str, difficulty: str, min_level: int,
    total_slots: int, party_split: int | None, gates: int,
) -> dict:
    return await _admin_post(
        "difficulties/add", discord_id, raid_name=raid_name, difficulty=difficulty,
        min_level=min_level, total_slots=total_slots, party_split=party_split, gates=gates,
    )


async def admin_delete_difficulty(discord_id: str, raid_name: str, difficulty: str) -> dict:
    return await _admin_post("difficulties/delete", discord_id, raid_name=raid_name, difficulty=difficulty)


async def admin_add_class(discord_id: str, name: str, is_support: bool) -> dict:
    return await _admin_post("classes/add", discord_id, name=name, is_support=is_support)


async def admin_delete_class(discord_id: str, name: str) -> dict:
    return await _admin_post("classes/delete", discord_id, name=name)


# ── 관리자 공대 관리 ─────────────────────────────────────────
# 강제 마감/재개/강퇴/파티장위임/일정변경은 새 함수를 안 만든다 — 위쪽의 기존
# close_party/reopen_party/kick_member/transfer_leader/reschedule_party가
# discord_id만 관리자 것으로 바꿔 보내면 봇 서버가 그대로 받아준다
# (bot/ui/views.py의 _require_leader_or_admin).

async def admin_list_parties(guild_id: str, discord_id: str) -> dict:
    resp = await _get_client().get(
        f"{config.BOT_API_BASE_URL}/api/internal/admin/parties",
        params={"guild_id": guild_id, "discord_id": discord_id},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def admin_revert_clear(message_id: str, discord_id: str) -> dict:
    resp = await _get_client().post(
        f"{config.BOT_API_BASE_URL}/api/internal/admin/parties/{message_id}/revert-clear",
        json={"discord_id": discord_id},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
