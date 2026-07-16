"""캐릭터 상세 정보(스킬/아크패시브/장신구/보석) 조회 — 웹 캐릭터 상세 페이지가 사용.

이전에는 페이지를 열 때(F5 포함)마다 로스트아크 API를 실시간 호출했다. 뷰당 1회
호출이라 API 한도(키당 분당 100건) 자체는 문제없었지만, 사용자 쪽에서 "동기화
버튼을 눌러야만 갱신되게 해달라"고 요청해 캐시 우선 조회 방식으로 바꿨다 —
get_character_armory_detail은 캐시가 있으면 그걸 그대로 반환하고, "동기화" 버튼이
호출하는 sync_character_armory_detail만 실제로 API를 호출한다.

부계정 지원 이후 캐릭터마다 API 키가 다를 수 있어서, expedition.resolve_character_account로
이 캐릭터가 실제로 속한 계정을 먼저 찾은 뒤 그 키로 아머리를 조회한다.
"""
import bot.api.lostark as loa
import bot.database.manager as db
from bot.api.armory_parser import parse_armory_detail
from bot.services.expedition import resolve_character_account


async def get_character_armory_detail(discord_id: str, character_name: str) -> dict:
    """반환: 성공 시 파싱된 아머리 정보 dict, 실패 시 {"error": "메시지"}.
    캐시가 있으면 API를 호출하지 않고 그대로 반환한다. 캐시가 아예 없는 최초 조회일 때만
    한 번 자동으로 채워준다(빈 화면을 보여주지 않기 위함) — 그 다음부터는 반드시
    "동기화" 버튼(sync_character_armory_detail)을 눌러야 최신 정보로 갱신된다."""
    cached = await db.get_character_armory_cache(discord_id, character_name)
    if cached:
        detail = cached["detail"]
        detail["synced_at"] = cached["synced_at"]
        return detail
    return await sync_character_armory_detail(discord_id, character_name)


async def sync_character_armory_detail(discord_id: str, character_name: str) -> dict:
    """로스트아크 API를 실제로 호출해 최신 정보로 캐시를 갱신한다. "동기화" 버튼 전용 —
    페이지를 그냥 열기만 해서는(캐시가 있는 한) 호출되지 않는다."""
    _, api_key_id, error = await resolve_character_account(discord_id, character_name)
    if error:
        return {"error": error}

    api_key = await db.get_user_api_key_by_id(api_key_id)
    if not api_key:
        return {"error": "API 키를 찾을 수 없습니다."}

    try:
        raw = await loa.get_armory(api_key, character_name, filters=loa.ARMORY_DETAIL_FILTERS)
    except RuntimeError as e:
        return {"error": str(e)}

    if raw is None:
        return {"error": "캐릭터 정보를 찾을 수 없습니다."}

    detail = parse_armory_detail(raw)

    # 이 조회에는 이미 전투력이 들어있으니, 랭킹 캐시를 공짜로 최신화한다(추가 API 호출 없음).
    raw_cp = (raw.get("ArmoryProfile") or {}).get("CombatPower")
    try:
        cp = int(float(raw_cp))
    except (TypeError, ValueError):
        cp = None
    if cp:
        updated = await db.update_character_combat_power(discord_id, character_name, cp)
        if not updated:
            # user_characters에 (discord_id, character_name) 행이 없어 갱신이 반영되지 않음
            # — 랭킹에서 이 캐릭터가 계속 안 보이는 원인이 될 수 있어 눈에 보이게 남긴다.
            print(
                f"[armory] combat_power 갱신 실패(매칭 행 없음): discord_id={discord_id}, "
                f"character_name={character_name!r} — 원정대에 등록되지 않은 캐릭터일 수 있음"
            )

    cached_ok = await db.set_character_armory_cache(discord_id, character_name, detail)
    if not cached_ok:
        print(
            f"[armory] 상세 캐시 저장 실패(매칭 행 없음): discord_id={discord_id}, "
            f"character_name={character_name!r}"
        )
        detail["synced_at"] = None
    else:
        cached = await db.get_character_armory_cache(discord_id, character_name)
        detail["synced_at"] = cached["synced_at"] if cached else None

    return detail
