"""로스트아크 오픈API 응답 구조 확인용 1회성 스크립트.

이번 조사 목적: 캐릭터 상세 페이지를 실제 아머리 사이트처럼 "장비/스킬/아크그리드/보석"
탭 구조로 재구성하기 위해, 아직 안 다뤄본 부분을 확인한다 —
1. 무기/방어구(투구·상의·하의·장갑·어깨) 장비 Tooltip 구조 (연마 효과, 초월, 엘릭서 등)
2. 우상단 "효과 양수지"(공격력/이동속도 등 전체 합산치) 박스에 대응하는 데이터가
   API에 별도 필드로 있는지, 아니면 여러 곳(장비/각인/카드/보석)의 효과를 직접 합산해야
   하는지 확인
3. ArmoryEngraving(각인) 구조

사용법: python scripts/inspect_armory.py <API키> <캐릭터명>
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from bot.api.lostark import _enc, _get  # noqa: E402


async def main(api_key: str, character_name: str) -> None:
    data = await _get(api_key, f"/armories/characters/{_enc(character_name)}")
    if data is None:
        print("응답 없음 (404) — 캐릭터명을 정확히 입력했는지 확인해주세요.")
        return

    print("=== 최상위 키 전체 목록 ===")
    for key, value in data.items():
        if isinstance(value, dict):
            print(f"{key}: dict, keys={list(value.keys())}")
        elif isinstance(value, list):
            print(f"{key}: list, len={len(value)}")
        else:
            print(f"{key}: {type(value).__name__}")

    # ── 무기/방어구 Tooltip 전체 (하나씩) ──────────────────────
    equipment = data.get("ArmoryEquipment") or []
    weapon_armor_types = {"무기", "투구", "상의", "하의", "장갑", "어깨"}
    print("\n=== ArmoryEquipment: 무기/방어구 각 부위 최상위 필드 ===")
    for item in equipment:
        if item.get("Type") in weapon_armor_types:
            print(f"\n[{item.get('Type')}] {item.get('Name')} (Grade={item.get('Grade')})")
            print(f"  keys={list(item.keys())}")

    print("\n=== 무기 Tooltip 전체 (첫 번째 무기/방어구 아이템) ===")
    for item in equipment:
        if item.get("Type") in weapon_armor_types:
            print(f"[{item.get('Type')}] {item.get('Name')}")
            print(item.get("Tooltip", "")[:8000])
            break

    print("\n=== 방어구 Tooltip 전체 (무기가 아닌 두 번째 부위) ===")
    seen_first = False
    for item in equipment:
        if item.get("Type") in weapon_armor_types:
            if not seen_first:
                seen_first = True
                continue
            print(f"[{item.get('Type')}] {item.get('Name')}")
            print(item.get("Tooltip", "")[:8000])
            break

    # ── ArmoryProfile 전체 (Stats/Tendencies에 합산 효과가 있는지 확인) ──
    print("\n=== ArmoryProfile 전체 ===")
    profile = data.get("ArmoryProfile") or {}
    print(json.dumps(profile, ensure_ascii=False, indent=2)[:4000])

    # ── ArmoryEngraving(각인) 구조 ──────────────────────────
    print("\n=== ArmoryEngraving 전체 ===")
    engraving = data.get("ArmoryEngraving") or {}
    print(json.dumps(engraving, ensure_ascii=False, indent=2)[:4000])

    # ── ArmoryCard(카드) 구조 ──────────────────────────────
    print("\n=== ArmoryCard 전체 ===")
    card = data.get("ArmoryCard") or {}
    print(json.dumps(card, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/inspect_armory.py <API키> <캐릭터명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
