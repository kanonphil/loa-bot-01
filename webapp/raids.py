"""모집 화면에서 쓰는 레이드 정렬 — 봇의 bot/data/raids.py:recruit_order와 같은 규칙.

봇 서버와 webapp은 서로 다른 머신이라 봇 코드를 직접 import하지 않는다
(webapp/raid_check.py가 get_applicable_raids를 재구현한 것과 같은 이유).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def is_recruitable(raid_info: dict, now: datetime | None = None) -> bool:
    """모집 목록에 띄울 레이드인지 — 비활성이거나 익스트림 기간이 지났으면 뺀다."""
    if not raid_info.get("is_active", True):
        return False
    if raid_info.get("is_extreme"):
        until = raid_info.get("available_until")
        if until:
            try:
                if datetime.fromisoformat(until) < (now or datetime.now(KST)):
                    return False
            except (TypeError, ValueError):
                pass
    return True


def recruit_order(raids: dict, now: datetime | None = None) -> list[tuple[str, dict]]:
    """공대 개설 화면에 보여줄 레이드를 표시 순서대로.

    raids 자체가 이미 카테고리 → 관리자가 정한 sort_order 순으로 내려오므로,
    여기서는 상단 고정(is_pinned)만 앞으로 끌어올린다."""
    items = [(n, i) for n, i in raids.items() if is_recruitable(i, now)]
    return [x for x in items if x[1].get("is_pinned")] + [
        x for x in items if not x[1].get("is_pinned")
    ]


def min_level(raid_info: dict) -> int | None:
    levels = [d["min_level"] for d in (raid_info.get("difficulties") or {}).values()]
    return min(levels) if levels else None


def picker_groups(raids: dict, item_level: float | None = None, now=None) -> list[dict]:
    """공대 개설 레이드 선택기용 — 상단 고정을 먼저, 그다음 카테고리 순으로 묶는다.

    item_level을 주면 난이도마다 입장 가능 여부(enterable)를 함께 계산한다.
    막는 게 아니라 표시만 — 실제 참여 자격은 봇 API가 다시 검증한다."""
    ordered = recruit_order(raids, now)
    pinned = [(n, i) for n, i in ordered if i.get("is_pinned")]

    groups: list[dict] = []
    if pinned:
        groups.append({"label": "자주 여는 레이드", "pinned": True, "raids": pinned})

    seen: list[str] = []
    for _, info in ordered:
        if info["category"] not in seen:
            seen.append(info["category"])
    for category in seen:
        entries = [
            (n, i) for n, i in ordered
            if i["category"] == category and not i.get("is_pinned")
        ]
        if entries:
            groups.append({"label": category, "pinned": False, "raids": entries})

    return [
        {
            "label": g["label"],
            "pinned": g["pinned"],
            "raids": [_raid_entry(name, info, item_level) for name, info in g["raids"]],
        }
        for g in groups
    ]


def _raid_entry(name: str, info: dict, item_level: float | None) -> dict:
    diffs = []
    for diff_name, diff in (info.get("difficulties") or {}).items():
        diffs.append(
            {
                "name": diff_name,
                "min_level": diff["min_level"],
                "total_slots": diff["total_slots"],
                "party_split": diff.get("party_split"),
                "gates": diff.get("gates", 1),
                "enterable": item_level is None or item_level >= diff["min_level"],
            }
        )
    return {
        "raid_name": name,
        "short_name": info.get("short_name") or name,
        "icon": info.get("icon") or "⚔️",
        "category": info["category"],
        "is_pinned": bool(info.get("is_pinned")),
        "min_level": min_level(info),
        "difficulties": diffs,
        "enterable": any(d["enterable"] for d in diffs) if diffs else False,
    }
