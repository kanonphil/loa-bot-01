"""로스트아크 오픈API 응답 구조 확인용 1회성 스크립트 (10번 항목 검토).
사용법: python scripts/inspect_armory.py <API키> <캐릭터명>
확장된 필터(profiles+equipment+combat-skills+arkpassive+engravings+cards+gems)로 응답을 받아서
각 섹션의 최상위 키만 출력한다 — 실제 값은 안 찍으므로 민감정보 노출 없음.
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from bot.api.lostark import _enc, _get  # noqa: E402


async def main(api_key: str, character_name: str) -> None:
    filters = "profiles+equipment+combat-skills+arkpassive+engravings+cards+gems"
    data = await _get(
        api_key, f"/armories/characters/{_enc(character_name)}", params={"filters": filters}
    )
    if data is None:
        print("응답 없음 (404) — 캐릭터명을 정확히 입력했는지 확인해주세요.")
        return

    for key, value in data.items():
        if isinstance(value, dict):
            print(f"{key}: dict, keys={list(value.keys())}")
        elif isinstance(value, list):
            print(f"{key}: list, len={len(value)}")
            if value:
                first = value[0]
                if isinstance(first, dict):
                    print(f"  [0] keys={list(first.keys())}")
        else:
            print(f"{key}: {type(value).__name__}")

    # ── 장신구(목걸이/귀걸이/반지/팔찌) Tooltip 전체 — 품질%/연마옵션이
    # Tooltip HTML 안에 어떤 형식으로 박혀있는지 확인용
    print("\n--- ArmoryEquipment: 장신구 Tooltip 전체 ---")
    accessory_types = {"목걸이", "귀걸이", "반지", "팔찌"}
    for item in data.get("ArmoryEquipment", []):
        if item.get("Type") in accessory_types:
            print(f"\n[{item['Type']}] {item['Name']} (Grade={item.get('Grade')})")
            print(item.get("Tooltip", "")[:4000])
            break  # 하나만 봐도 형식 파악 충분

    # ── 보석 구조 확인
    print("\n--- ArmoryGem: Gems[0] 전체 ---")
    gems = data.get("ArmoryGem") or {}
    gem_list = gems.get("Gems") or []
    if gem_list:
        print(json.dumps(gem_list[0], ensure_ascii=False, indent=2)[:2000])
    else:
        print("장착된 보석 없음")

    # ── 룬이 장착된 스킬 찾기 (Rune이 null이 아닌 첫 번째)
    print("\n--- ArmorySkills: 룬 장착된 스킬 예시 ---")
    found_rune = False
    for skill in data.get("ArmorySkills", []):
        if skill.get("Rune"):
            print(f"스킬: {skill['Name']} (Lv.{skill['Level']})")
            print(json.dumps(skill["Rune"], ensure_ascii=False, indent=2)[:1500])
            selected_tripods = [t for t in skill.get("Tripods", []) if t.get("IsSelected")]
            print(f"선택된 트라이포드 개수: {len(selected_tripods)}")
            for t in selected_tripods:
                print(f"  - Tier {t['Tier']}: {t['Name']}")
            found_rune = True
            break
    if not found_rune:
        print("룬이 장착된 스킬을 찾지 못함 (전부 미장착이거나 이 캐릭터는 룬 미보유)")

    # 그래도 선택된 트라이포드 예시 하나는 보여주기 (룬 여부와 무관)
    print("\n--- ArmorySkills: 선택된 트라이포드가 있는 스킬 예시 ---")
    for skill in data.get("ArmorySkills", []):
        selected = [t for t in skill.get("Tripods", []) if t.get("IsSelected")]
        if selected and skill.get("Level", 0) > 1:
            print(f"스킬: {skill['Name']} (Lv.{skill['Level']})")
            for t in selected:
                print(f"  - Tier {t['Tier']} Slot {t['Slot']}: {t['Name']}")
            break


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/inspect_armory.py <API키> <캐릭터명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
