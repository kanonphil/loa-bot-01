"""캐릭터 상세 정보(스킬/아크패시브/장신구/보석) 조회 — 웹 캐릭터 상세 페이지가 사용.

부계정 지원 이후 캐릭터마다 API 키가 다를 수 있어서, expedition.resolve_character_account로
이 캐릭터가 실제로 속한 계정을 먼저 찾은 뒤 그 키로 아머리를 조회한다.
"""
import bot.api.lostark as loa
import bot.database.manager as db
from bot.api.armory_parser import parse_armory_detail
from bot.services.expedition import resolve_character_account


async def get_character_armory_detail(discord_id: str, character_name: str) -> dict:
    """반환: 성공 시 파싱된 아머리 정보 dict, 실패 시 {"error": "메시지"}."""
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

    return parse_armory_detail(raw)
