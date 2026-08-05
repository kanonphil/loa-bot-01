"""webapp/raids.py — 공대 개설 레이드 선택기의 정렬/그룹핑.

관리자가 정한 순서(카테고리 → sort_order)를 그대로 따르고, 상단 고정만 앞으로 뺀다.
봇의 bot/data/raids.py:recruit_order와 같은 규칙이어야 한다.
"""
from datetime import datetime, timedelta

from webapp.raids import KST, is_recruitable, min_level, picker_groups, recruit_order

NOW = datetime(2026, 8, 5, 14, 0, tzinfo=KST)


def _raid(category="카제로스", pinned=False, active=True, levels=(1700,), **over):
    return {
        "short_name": "약칭", "icon": "⚔️", "category": category,
        "is_extreme": False, "is_active": active,
        "available_from": None, "available_until": None,
        "is_pinned": pinned,
        "difficulties": {
            f"난이도{i}": {"min_level": lv, "total_slots": 8, "party_split": 4, "gates": 2}
            for i, lv in enumerate(levels)
        },
        **over,
    }


def test_order_follows_dict_order():
    """봇이 이미 카테고리 → sort_order 순으로 내려주므로 그 순서를 뒤집지 않는다."""
    raids = {"3막": _raid(), "1막": _raid(), "2막": _raid()}
    assert [n for n, _ in recruit_order(raids)] == ["3막", "1막", "2막"]


def test_pinned_comes_first():
    raids = {"1막": _raid(), "2막": _raid(), "종막": _raid(pinned=True)}
    assert [n for n, _ in recruit_order(raids)] == ["종막", "1막", "2막"]


def test_inactive_is_excluded():
    raids = {"1막": _raid(), "옛레이드": _raid(active=False)}
    assert [n for n, _ in recruit_order(raids)] == ["1막"]


def test_expired_extreme_is_excluded():
    expired = _raid(is_extreme=True, available_until=(NOW - timedelta(days=1)).isoformat())
    live = _raid(is_extreme=True, available_until=(NOW + timedelta(days=1)).isoformat())
    raids = {"지난이벤트": expired, "진행이벤트": live}
    assert [n for n, _ in recruit_order(raids, NOW)] == ["진행이벤트"]


def test_extreme_without_period_stays():
    raids = {"기간없음": _raid(is_extreme=True)}
    assert is_recruitable(raids["기간없음"], NOW) is True


def test_min_level_uses_lowest_difficulty():
    assert min_level(_raid(levels=(1700, 1660, 1720))) == 1660
    assert min_level(_raid(levels=())) is None


# ── 그룹핑 ───────────────────────────────────────────────

def test_groups_put_pinned_section_first():
    raids = {
        "1막": _raid(category="카제로스"),
        "카양겔": _raid(category="어비스"),
        "종막": _raid(category="카제로스", pinned=True),
    }
    groups = picker_groups(raids)
    assert [g["label"] for g in groups] == ["자주 여는 레이드", "카제로스", "어비스"]
    # 고정된 레이드는 카테고리 그룹에서 중복되지 않는다
    assert [r["raid_name"] for r in groups[1]["raids"]] == ["1막"]


def test_groups_keep_category_order_from_source():
    raids = {"카양겔": _raid(category="어비스"), "1막": _raid(category="카제로스")}
    assert [g["label"] for g in picker_groups(raids)] == ["어비스", "카제로스"]


def test_entries_mark_enterable_per_difficulty():
    raids = {"종막": _raid(levels=(1700, 1740))}
    entry = picker_groups(raids, item_level=1720)[0]["raids"][0]
    assert [d["enterable"] for d in entry["difficulties"]] == [True, False]
    assert entry["enterable"] is True


def test_entry_not_enterable_when_all_difficulties_too_high():
    raids = {"미래": _raid(levels=(9999,))}
    entry = picker_groups(raids, item_level=1720)[0]["raids"][0]
    assert entry["enterable"] is False


def test_without_item_level_everything_is_enterable():
    raids = {"미래": _raid(levels=(9999,))}
    entry = picker_groups(raids)[0]["raids"][0]
    assert entry["enterable"] is True


def test_raid_without_difficulty_does_not_crash():
    raids = {"난이도없음": _raid(levels=())}
    entry = picker_groups(raids, item_level=1720)[0]["raids"][0]
    assert entry["difficulties"] == []
    assert entry["enterable"] is False
    assert entry["min_level"] is None
