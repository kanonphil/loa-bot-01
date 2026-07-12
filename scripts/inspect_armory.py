"""로스트아크 오픈API 응답 구조 확인용 1회성 스크립트.

이번 조사 목적: ArmoryEquipment 16개 항목 중 지금까지 처리 못한 것들
(팔찌/어빌리티 스톤/무기에 붙는 보주 등)의 실제 Type 이름과 Tooltip 구조를 확인하고,
ArmoryCard.Effects의 실제 구조(카드 세트효과)도 확인한다.

사용법: python scripts/inspect_armory.py <API키> <캐릭터명>
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from bot.api.lostark import _enc, _get  # noqa: E402

_ALREADY_HANDLED_TYPES = {"무기", "투구", "상의", "하의", "장갑", "어깨", "목걸이", "귀걸이", "반지"}


async def main(api_key: str, character_name: str) -> None:
    data = await _get(api_key, f"/armories/characters/{_enc(character_name)}")
    if data is None:
        print("응답 없음 (404) — 캐릭터명을 정확히 입력했는지 확인해주세요.")
        return

    equipment = data.get("ArmoryEquipment") or []
    print(f"=== ArmoryEquipment 총 {len(equipment)}개 — Type별 개수 ===")
    type_counts: dict[str, int] = {}
    for item in equipment:
        t = item.get("Type")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, count in type_counts.items():
        handled = "처리중" if t in _ALREADY_HANDLED_TYPES else "★ 미처리"
        print(f"  {t}: {count}개  [{handled}]")

    print("\n=== 아직 처리 못한 Type의 아이템 전체 (Name/Icon/Tooltip) ===")
    for item in equipment:
        t = item.get("Type")
        if t in _ALREADY_HANDLED_TYPES:
            continue
        print(f"\n[{t}] {item.get('Name')} (Grade={item.get('Grade')})")
        print(f"  keys={list(item.keys())}")
        print(f"  Icon={item.get('Icon')}")
        print(f"  Tooltip:\n{item.get('Tooltip', '')[:6000]}")

    # ── 무기에 붙는 "보주" 정보가 무기 아이템 Tooltip 안에 섞여 있는지,
    # 아니면 ArmoryEquipment의 별도 항목인지 확인 (위에서 이미 안 잡혔다면 여기 확인)
    print("\n=== 무기 아이템 전체 Tooltip (보주 정보 포함 여부 확인) ===")
    for item in equipment:
        if item.get("Type") == "무기":
            print(item.get("Tooltip", "")[:8000])
            break

    # ── ArmoryCard.Effects 실제 구조 확인 (카드 세트효과) ──
    print("\n=== ArmoryCard.Effects 전체 (카드 세트효과 구조 확인) ===")
    card = data.get("ArmoryCard") or {}
    print(json.dumps(card.get("Effects"), ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/inspect_armory.py <API키> <캐릭터명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
