"""webapp.raid_check의 순수 로직(applicable_raids/group_by_category) 검증.
봇의 bot/data/raids.py:get_applicable_raids와 동일한 결과를 내야 한다.
"""
from datetime import datetime, timedelta, timezone

from webapp.raid_check import applicable_raids, group_by_category

KST = timezone(timedelta(hours=9))

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막",
        "icon": "🗡️",
        "category": "카제로스",
        "is_extreme": False,
        "is_active": True,
        "available_from": None,
        "available_until": None,
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2},
            "하드": {"min_level": 1720, "total_slots": 8, "party_split": 4, "gates": 2},
        },
    },
    "종막": {
        "short_name": "종막",
        "icon": "🗡️",
        "category": "카제로스",
        "is_extreme": False,
        "is_active": True,
        "available_from": None,
        "available_until": None,
        "difficulties": {"노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "비활성 레이드": {
        "short_name": "비활성",
        "icon": "⚫",
        "category": "카제로스",
        "is_extreme": False,
        "is_active": False,
        "available_from": None,
        "available_until": None,
        "difficulties": {"노말": {"min_level": 1, "total_slots": 8, "party_split": None, "gates": 1}},
    },
}

CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}]


def test_filters_by_min_level():
    result = applicable_raids(RAIDS, item_level=1710.0)
    names = {(r, d) for r, d, _ in result}
    assert ("아르모체(4막)", "노말") in names
    assert ("종막", "노말") in names
    assert ("아르모체(4막)", "하드") not in names  # 1720 미달


def test_excludes_inactive_raid_regardless_of_level():
    result = applicable_raids(RAIDS, item_level=9999.0)
    names = {r for r, _, _ in result}
    assert "비활성 레이드" not in names


def test_extreme_raid_excluded_after_available_until():
    raids = {
        **RAIDS,
        "익스트림": {
            "short_name": "익스트림",
            "icon": "⚡",
            "category": "카제로스",
            "is_extreme": True,
            "is_active": True,
            "available_from": None,
            "available_until": (datetime.now(KST) - timedelta(days=1)).isoformat(),
            "difficulties": {"노말": {"min_level": 1, "total_slots": 8, "party_split": None, "gates": 1}},
        },
    }
    result = applicable_raids(raids, item_level=9999.0)
    names = {r for r, _, _ in result}
    assert "익스트림" not in names


def test_extreme_raid_included_before_available_until():
    raids = {
        **RAIDS,
        "익스트림": {
            "short_name": "익스트림",
            "icon": "⚡",
            "category": "카제로스",
            "is_extreme": True,
            "is_active": True,
            "available_from": None,
            "available_until": (datetime.now(KST) + timedelta(days=1)).isoformat(),
            "difficulties": {"노말": {"min_level": 1, "total_slots": 8, "party_split": None, "gates": 1}},
        },
    }
    result = applicable_raids(raids, item_level=9999.0)
    names = {r for r, _, _ in result}
    assert "익스트림" in names


def test_group_by_category_groups_and_orders():
    applicable = applicable_raids(RAIDS, item_level=1720.0)
    groups = group_by_category(RAIDS, CATEGORIES, applicable)

    assert len(groups) == 1
    assert groups[0]["category"] == "카제로스"
    raid_names = [r["raid_name"] for r in groups[0]["raids"]]
    assert "아르모체(4막)" in raid_names
    assert "종막" in raid_names
    assert "비활성 레이드" not in raid_names


def test_group_by_category_skips_category_with_nothing_applicable():
    low_level_raids = {"아르모체(4막)": RAIDS["아르모체(4막)"]}
    groups = group_by_category(low_level_raids, CATEGORIES, applicable_raids(low_level_raids, item_level=1.0))
    assert groups == []
