"""로스트아크 오픈 API의 armory profiles 응답에 길드 관련 필드가 있는지
값 노출 없이 키 이름만 확인하는 일회성 진단 스크립트.
사용법 (봇 서버에서): python -m scripts.check_guild_field <디스코드ID> <캐릭터명>
확인 후 삭제해도 됩니다.
"""
import asyncio
import sys

sys.path.insert(0, ".")

import bot.database.manager as db
import bot.api.lostark as loa


async def main(discord_id: str, character_name: str) -> None:
    api_key = await db.get_user_api_key(discord_id)
    if not api_key:
        print("등록된 API 키가 없습니다.")
        return

    armory = await loa.get_armory(api_key, character_name)
    if not armory:
        print("캐릭터 정보를 가져오지 못했습니다.")
        return

    profile = armory.get("ArmoryProfile", {})
    print("ArmoryProfile 필드 목록:")
    for key in profile.keys():
        print(f"  - {key}")

    guild_related = {k: v for k, v in profile.items() if "guild" in k.lower()}
    print()
    if guild_related:
        print("길드 관련 필드 발견:", list(guild_related.keys()))
    else:
        print("길드 관련 필드 없음.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
