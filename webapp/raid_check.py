"""레이드 체크 페이지의 순수 로직.
봇의 bot/data/raids.py:get_applicable_raids와 동일한 규칙을 재구현한 것 —
봇 서버와 webapp은 서로 다른 머신이라 봇 코드를 직접 import하지 않는다.
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def applicable_raids(raids: dict, item_level: float) -> list[tuple[str, str, dict]]:
    """캐릭터 아이템레벨 기준으로 입장 가능한 (레이드명, 난이도명, 난이도정보) 목록."""
    now = datetime.now(KST)
    result = []
    for raid_name, raid_info in raids.items():
        if not raid_info.get("is_active", True):
            continue
        if raid_info.get("is_extreme"):
            until = raid_info.get("available_until")
            if until:
                try:
                    if datetime.fromisoformat(until) < now:
                        continue
                except ValueError:
                    pass
        for diff_name, diff_info in raid_info["difficulties"].items():
            if item_level >= diff_info["min_level"]:
                result.append((raid_name, diff_name, diff_info))
    return result


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
