"""전투력(CombatPower) 원본 값 확인용 1회성 스크립트.

랭킹에 926, 447처럼 실제 게임 화면과 자릿수가 다른 작은 값이 저장되는 문제를
진단하기 위해, 로스트아크 오픈API가 ArmoryProfile.CombatPower로 실제 어떤 값
(타입/자릿수)을 내려주는지 그대로 출력한다.

사용법: python scripts/inspect_combat_power.py <API키> <캐릭터명>
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from bot.api.lostark import _enc, _get  # noqa: E402


async def main(api_key: str, character_name: str) -> None:
    data = await _get(
        api_key, f"/armories/characters/{_enc(character_name)}", params={"filters": "profiles"}
    )
    if data is None:
        print("응답 없음 (404) — 캐릭터명을 정확히 입력했는지 확인해주세요.")
        return

    profile = data.get("ArmoryProfile") or {}
    raw_cp = profile.get("CombatPower")

    print("=== ArmoryProfile 전체 (참고용) ===")
    print(json.dumps(profile, ensure_ascii=False, indent=2))

    print("\n=== CombatPower 필드만 ===")
    print(f"타입: {type(raw_cp).__name__}")
    print(f"원본 값: {raw_cp!r}")
    try:
        print(f"int(float(...)) 변환 결과: {int(float(raw_cp)):,}")
    except (TypeError, ValueError) as e:
        print(f"int(float(...)) 변환 실패: {e}")

    print(
        "\n이 원본 값이 게임 내 전투정보실에서 보는 실제 전투력(보통 수백만~수천만 단위)과\n"
        "다르다면, 이 필드는 우리가 기대하던 '게임 화면의 전투력'이 아닐 수 있습니다."
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/inspect_combat_power.py <API키> <캐릭터명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
