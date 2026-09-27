"""레이드 체크 페이지의 순수 로직.
봇의 bot/data/raids.py:get_applicable_raids와 동일한 규칙을 재구현한 것 —
봇 서버와 webapp은 서로 다른 머신이라 봇 코드를 직접 import하지 않는다.
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def _parse_aware(value: str | None) -> datetime | None:
    """운영 기간 문자열 → aware datetime. naive면 KST로 간주(aware와 비교하다 TypeError 나지 않게)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt


def is_extreme_available(raid_info: dict, now: datetime | None = None) -> bool:
    """익스트림 운영 중인지 — 활성 + available_from ≤ now ≤ available_until (각 경계는 없을 수 있음)."""
    if not raid_info.get("is_active", True):
        return False
    now = now or datetime.now(KST)
    start = _parse_aware(raid_info.get("available_from"))
    end = _parse_aware(raid_info.get("available_until"))
    if start and now < start:
        return False
    if end and end < now:
        return False
    return True


def applicable_raids(raids: dict, item_level: float, include_extreme: bool = False) -> list[tuple[str, str, dict]]:
    """캐릭터 아이템레벨 기준으로 입장 가능한 (레이드명, 난이도명, 난이도정보) 목록.
    익스트림은 원정대당 주 1회라 캐릭터 카드에 맞지 않아 기본 제외 — extreme_raids()가 따로 다룬다."""
    now = datetime.now(KST)
    result = []
    for raid_name, raid_info in raids.items():
        if not raid_info.get("is_active", True):
            continue
        if raid_info.get("is_extreme"):
            if not include_extreme or not is_extreme_available(raid_info, now):
                continue
        for diff_name, diff_info in raid_info["difficulties"].items():
            if item_level >= diff_info["min_level"]:
                result.append((raid_name, diff_name, diff_info))
    return result


def extreme_raids(raids: dict, now: datetime | None = None) -> list[dict]:
    """지금 운영 중인 익스트림 레이드(레이드 선택과 무관) — 원정대 섹션 카드 재료."""
    now = now or datetime.now(KST)
    return [
        {
            "raid_name": name,
            "short_name": info.get("short_name") or name,
            "icon": info.get("icon"),
            "available_from": info.get("available_from"),
            "available_until": info.get("available_until"),
            "difficulties": list((info.get("difficulties") or {}).items()),
        }
        for name, info in raids.items()
        if info.get("is_extreme") and is_extreme_available(info, now)
    ]


def eligible_characters(characters: list[dict], min_level: float) -> list[dict]:
    """입장 레벨 이상인 캐릭터만 — 익스트림 체크 폼의 캐릭터 선택지."""
    return [c for c in characters if (c.get("item_level") or 0) >= min_level]


def filter_groups_by_selection(groups: list[dict], selection: dict) -> list[dict]:
    """캐릭터가 "레이드 선택"에서 고른 레이드만 남긴다. 한 번도 커스터마이즈
    안 했으면(selection["customized"] == False) 그대로 전체를 반환 — 레이드 체크
    카드와 메인 대시보드 진행률이 항상 같은 기준으로 계산되도록 공용으로 쓴다.
    선택된 레이드가 하나도 없는(빈) 카테고리는 통째로 뺀다."""
    if not selection["customized"]:
        return groups
    selected = set(selection["selected_raids"])
    filtered = []
    for g in groups:
        raids = [r for r in g["raids"] if r["raid_name"] in selected]
        if raids:
            filtered.append({**g, "raids": raids})
    return filtered


def group_by_category(
    raids: dict, categories: list[dict], applicable: list[tuple[str, str, dict]]
) -> list[dict]:
    """카테고리 순서대로 그룹핑해서 템플릿에서 바로 쓸 수 있는 구조로 변환."""
    applicable_by_raid: dict[str, list[tuple[str, dict]]] = {}
    for raid_name, diff_name, diff_info in applicable:
        applicable_by_raid.setdefault(raid_name, []).append((diff_name, diff_info))

    groups = []
    for cat in categories:
        raid_entries = []
        for raid_name, raid_info in raids.items():
            if raid_info["category"] != cat["name"]:
                continue
            diffs = applicable_by_raid.get(raid_name)
            if not diffs:
                continue
            raid_entries.append(
                {
                    "raid_name": raid_name,
                    "short_name": raid_info["short_name"],
                    "icon": raid_info["icon"],
                    "difficulties": diffs,
                }
            )
        if raid_entries:
            groups.append({"category": cat["name"], "raids": raid_entries})
    return groups
