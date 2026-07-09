"""로스트아크 오픈API 응답 구조 확인용 1회성 스크립트.

이번 조사 목적: 스킬/트라이포드 아이콘 이미지 필드 확인 + 아크그리드
(질서의 해/달/별, 혼돈의 해/달/별 + 장착 잼 스탯) 데이터가 어느 키에
어떤 구조로 들어있는지 찾기.

사용법: python scripts/inspect_armory.py <API키> <캐릭터명>

filters 파라미터를 아예 생략해서 API가 내려줄 수 있는 모든 섹션을
한 번에 받아온다 (필터 이름을 추측하지 않기 위함).
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from bot.api.lostark import _enc, _get  # noqa: E402


def _find_keys_containing(obj, needle: str, path: str = "$", found: list | None = None) -> list:
    """obj를 재귀 순회하며 키 이름에 needle(대소문자 무시)이 포함된 위치를 전부 찾는다."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_path = f"{path}.{key}"
            if needle.lower() in str(key).lower():
                found.append(new_path)
            _find_keys_containing(value, needle, new_path, found)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # 리스트는 앞 3개만 순회 (구조 파악에 충분)
            _find_keys_containing(item, needle, f"{path}[{i}]", found)
    return found


async def main(api_key: str, character_name: str) -> None:
    # filters 생략 → API가 지원하는 모든 섹션을 한 번에 받는다.
    data = await _get(api_key, f"/armories/characters/{_enc(character_name)}")
    if data is None:
        print("응답 없음 (404) — 캐릭터명을 정확히 입력했는지 확인해주세요.")
        return

    print("=== 최상위 키 전체 목록 (필터 없이 받은 전체 응답) ===")
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

    # ── "그리드" 관련 키를 전체 응답에서 재귀 검색 (어느 깊이에 있든 찾기 위함)
    print("\n=== '그리드'/Grid 관련 키 검색 결과 ===")
    grid_hits = _find_keys_containing(data, "grid")
    ark_hits = _find_keys_containing(data, "ark")
    for hit in sorted(set(grid_hits + ark_hits)):
        print(hit)
    if not grid_hits and not ark_hits:
        print("(관련 키를 찾지 못함 — 이 필터 세트에는 아크그리드 데이터가 없는 것으로 보임)")

    # ── ArkGrid.Effects 전체 (종합 스탯으로 추정되는 부분 — 안 잘리게 별도 출력)
    ark_grid = data.get("ArkGrid") or {}
    print("\n=== ArkGrid.Effects 전체 (잘림 없이) ===")
    print(json.dumps(ark_grid.get("Effects"), ensure_ascii=False, indent=2))

    # ── ArkGrid.Slots[0]의 Tooltip을 파싱해서 코어 타입/포인트/옵션 텍스트만 추출 (확인용)
    print("\n=== ArkGrid.Slots[0] 파싱 테스트 (코어 타입/포인트/옵션) ===")
    slots = ark_grid.get("Slots") or []
    if slots:
        slot0 = slots[0]
        tooltip = json.loads(slot0.get("Tooltip") or "{}")
        for el in tooltip.values():
            if isinstance(el, dict) and el.get("type") == "ItemPartBox":
                v = el.get("value") or {}
                print(f"{v.get('Element_000')} -> {v.get('Element_001')[:300]}")
        print(f"\nSlot Name: {slot0.get('Name')}, Point: {slot0.get('Point')}, Grade: {slot0.get('Grade')}")
        gems = slot0.get("Gems") or []
        if gems:
            gem0 = gems[0]
            gem_tooltip = json.loads(gem0.get("Tooltip") or "{}")
            print(f"\nGem[0] IsActive: {gem0.get('IsActive')}, Grade: {gem0.get('Grade')}")
            for el in gem_tooltip.values():
                if isinstance(el, dict) and el.get("type") == "ItemPartBox":
                    v = el.get("value") or {}
                    print(f"{v.get('Element_000')} -> {v.get('Element_001')[:300]}")

    # ── 최상위 Slots 개수와 각 Name만 요약 (6개: 질서 해/달/별, 혼돈 해/달/별인지 확인)
    print("\n=== ArkGrid.Slots 전체 이름 목록 ===")
    for s in slots:
        print(f"Index {s.get('Index')}: {s.get('Name')} (Point={s.get('Point')}, Grade={s.get('Grade')}, Gems={len(s.get('Gems') or [])})")

    # ── ArmorySkills: 스킬/트라이포드에 아이콘 필드가 있는지 확인
    print("\n=== ArmorySkills[0] 전체 키/값 (아이콘 필드 확인용) ===")
    skills = data.get("ArmorySkills") or []
    if skills:
        first_skill = skills[0]
        print(json.dumps({k: v for k, v in first_skill.items() if k != "Tripods"}, ensure_ascii=False, indent=2))
        tripods = first_skill.get("Tripods") or []
        if tripods:
            print("\n--- Tripods[0] 전체 키/값 ---")
            print(json.dumps(tripods[0], ensure_ascii=False, indent=2))
    else:
        print("ArmorySkills 데이터 없음")

    # 트라이포드 중 실제 선택된(IsSelected) 것 하나도 확인 — 아이콘 필드가
    # 선택 여부와 무관하게 항상 있는지 검증
    print("\n--- 선택된(IsSelected) 트라이포드 예시 (아이콘 포함 전체 필드) ---")
    for skill in skills:
        selected = [t for t in (skill.get("Tripods") or []) if t.get("IsSelected")]
        if selected:
            print(f"스킬: {skill.get('Name')}")
            print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            break

    # ── 보석 구조 재확인 (기존 ArmoryGem 외에 다른 곳에 스탯형 잼이 있는지)
    print("\n=== ArmoryGem 전체 구조 ===")
    gems = data.get("ArmoryGem") or {}
    print(json.dumps(gems, ensure_ascii=False, indent=2)[:3000])

    # ── ArkPassive 전체 구조 재확인 (그리드가 이 안에 통합되어 있을 가능성)
    print("\n=== ArkPassive 전체 구조 ===")
    ark_passive = data.get("ArkPassive") or {}
    print(json.dumps(ark_passive, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/inspect_armory.py <API키> <캐릭터명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
