"""API 키를 등록하지 않은 게스트를 공대에 초대할 때 캐릭터 정보를 조회한다.

로스트아크 오픈API의 캐릭터 조회는 "그 캐릭터의 키"가 아니라 아무 유효한 키로
아무 캐릭터나 조회할 수 있는 공개 조회라서, 관리자(config.GUEST_LOOKUP_DISCORD_ID)가
등록해둔 키 하나로 게스트가 입력한 닉네임의 직업/전투력/아이템레벨을 그대로 가져올 수 있다.
"""
import config
import bot.api.lostark as loa
import bot.database.manager as db


async def lookup_guest_character(character_name: str) -> dict:
    """반환: 성공 시 {"character_name", "character_class", "item_level", "combat_power"},
    실패 시 {"error": "메시지"}."""
    if not config.GUEST_LOOKUP_DISCORD_ID:
        return {"error": "게스트 초대 기능이 설정되지 않았습니다. 관리자에게 문의해주세요."}

    admin_key = await db.get_user_api_key(config.GUEST_LOOKUP_DISCORD_ID)
    if not admin_key:
        return {"error": "게스트 조회용 관리자 API 키를 찾을 수 없습니다. 관리자에게 문의해주세요."}

    try:
        armory = await loa.get_armory(admin_key, character_name, filters="profiles")
    except RuntimeError as e:
        return {"error": str(e)}

    if armory is None:
        return {"error": f"'{character_name}' 캐릭터를 찾을 수 없습니다. 이름을 다시 확인해주세요."}

    profile = armory.get("ArmoryProfile") or {}
    return {
        "character_name": profile.get("CharacterName") or character_name,
        "character_class": profile.get("CharacterClassName") or "?",
        "item_level": loa.parse_item_level(profile),
        "combat_power": profile.get("CombatPower"),
    }
