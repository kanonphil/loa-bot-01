"""공대 모집 레이드 Select의 25개 한도 분할 검증.

디스코드 Select는 옵션이 최대 25개다. 예전 RecruitView는 활성 레이드를 자르지 않고
전부 넣어서, 레이드가 26개가 되는 순간 /공대모집 자체가 예외로 죽었다.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import discord
import pytest

from bot.data import raids as raids_module
from bot.ui.views import RecruitView


def _raid(category: str = "카제로스", pinned: bool = False, active: bool = True) -> dict:
    return {
        "short_name": "약칭",
        "icon": "⚔️",
        "category": category,
        "is_extreme": False,
        "is_active": active,
        "available_from": None,
        "available_until": None,
        "sort_order": 0,
        "is_pinned": pinned,
        "difficulties": {"노말": {"min_level": 1600, "total_slots": 8,
                                  "party_split": 4, "gates": 2, "sort_order": 0}},
    }


@pytest.fixture()
def raids(monkeypatch):
    """RAIDS는 in-place 갱신 전제라 dict 내용만 바꾼다."""
    original = dict(raids_module.RAIDS)
    yield raids_module.RAIDS
    raids_module.RAIDS.clear()
    raids_module.RAIDS.update(original)


def _fill(raids: dict, count: int) -> None:
    raids.clear()
    for i in range(count):
        raids[f"레이드{i:02d}"] = _raid()


def _raid_select(view: RecruitView) -> discord.ui.Select:
    return view.children[0]


def test_under_limit_shows_all_raids_without_pager(raids):
    _fill(raids, 20)
    sel = _raid_select(RecruitView("1", "2"))
    assert len(sel.options) == 20
    assert all(o.value != RecruitView.MORE_VALUE for o in sel.options)


def test_exactly_at_limit_still_fits_in_one_page(raids):
    _fill(raids, 25)
    sel = _raid_select(RecruitView("1", "2"))
    assert len(sel.options) == 25
    assert all(o.value != RecruitView.MORE_VALUE for o in sel.options)


def test_over_limit_splits_into_pages(raids):
    """26개부터는 24개 + '더 보기' 1칸으로 끊는다 — 예전엔 여기서 죽었다."""
    _fill(raids, 30)
    view = RecruitView("1", "2")
    sel = _raid_select(view)
    assert len(sel.options) == RecruitView.SELECT_LIMIT
    assert [o.value for o in sel.options[:24]] == [f"레이드{i:02d}" for i in range(24)]
    assert sel.options[-1].value == RecruitView.MORE_VALUE


def test_next_page_shows_the_rest(raids):
    _fill(raids, 30)
    view = RecruitView("1", "2")
    view.raid_page = 1
    view._build()
    sel = _raid_select(view)
    values = [o.value for o in sel.options if o.value != RecruitView.MORE_VALUE]
    assert values == [f"레이드{i:02d}" for i in range(24, 30)]


def test_page_wraps_around(raids):
    _fill(raids, 30)
    view = RecruitView("1", "2")
    view.raid_page = 2  # 페이지는 2개뿐 — 넘치면 처음으로 돌아온다
    view._build()
    assert view.raid_page == 0
    assert _raid_select(view).options[0].value == "레이드00"


def test_no_option_count_ever_exceeds_discord_limit(raids):
    for count in [24, 25, 26, 48, 49, 50, 99]:
        _fill(raids, count)
        view = RecruitView("1", "2")
        pages = view._paginate(raids_module.recruit_order())
        for page_index in range(len(pages)):
            view.raid_page = page_index
            view._build()
            assert len(_raid_select(view).options) <= RecruitView.SELECT_LIMIT, count


def test_pinned_raid_comes_first_and_is_marked(raids):
    _fill(raids, 5)
    raids["레이드04"]["is_pinned"] = True
    sel = _raid_select(RecruitView("1", "2"))
    assert sel.options[0].value == "레이드04"
    assert sel.options[0].label.startswith("📌")


def test_inactive_raids_are_excluded(raids):
    _fill(raids, 5)
    raids["레이드02"]["is_active"] = False
    sel = _raid_select(RecruitView("1", "2"))
    assert "레이드02" not in [o.value for o in sel.options]


def test_raid_without_difficulty_does_not_crash(raids):
    """난이도를 아직 안 붙인 레이드가 있어도 모집 화면은 떠야 한다
    (예전엔 min()이 빈 시퀀스를 받아 ValueError)."""
    _fill(raids, 3)
    raids["레이드01"]["difficulties"] = {}
    sel = _raid_select(RecruitView("1", "2"))
    option = next(o for o in sel.options if o.value == "레이드01")
    assert "난이도 미등록" in option.description


def test_empty_raid_list_disables_select(raids):
    raids.clear()
    sel = _raid_select(RecruitView("1", "2"))
    assert sel.disabled
    assert len(sel.options) == 1
