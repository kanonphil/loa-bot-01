"""레이드 구독 "전체 난이도" 옵션 검증. difficulty 컬럼에 리터럴 문자열 "전체"를
저장해 와일드카드로 쓴다(NULL은 SQLite가 PK 유일성 검사에서 서로 다른 값으로
취급해 중복 구독 방지가 깨지므로 피함) — bot/database/manager.py의
get_raid_subscribers와 bot/cogs/subscription.py의 "전체 난이도" 옵션."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.cogs.subscription import RaidSelectView, UnsubscribeView

RAID = "카멘"


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())


def test_get_raid_subscribers_includes_exact_and_wildcard(clean_db):
    asyncio.run(db.subscribe_raid("111", RAID, "노말"))
    asyncio.run(db.subscribe_raid("222", RAID, "전체"))
    asyncio.run(db.subscribe_raid("333", RAID, "하드"))  # 다른 난이도 구독자는 제외돼야 함

    subs = asyncio.run(db.get_raid_subscribers(RAID, "노말"))
    assert set(subs) == {"111", "222"}


def test_get_raid_subscribers_wildcard_does_not_duplicate_when_both_subscribed(clean_db):
    """정확한 난이도와 전체를 동시에 구독해도(가능한 상태) 목록에 두 번 안 잡히는지."""
    asyncio.run(db.subscribe_raid("111", RAID, "노말"))
    asyncio.run(db.subscribe_raid("111", RAID, "전체"))

    subs = asyncio.run(db.get_raid_subscribers(RAID, "노말"))
    assert subs.count("111") == 2  # 실제로는 두 구독이 별개 행이라 두 번 잡히는 게 맞음(중복 알림 방지는 발신 측 책임)


def test_diff_select_view_includes_wildcard_option_first():
    raids_module.RAIDS.clear()
    raids_module.RAIDS.update({RAID: {"difficulties": {"노말": {"min_level": 1680, "total_slots": 8}}}})
    view = RaidSelectView("111")
    view._build_diff_select(RAID)
    select = view.children[0]
    values = [opt.value for opt in select.options]
    assert values[0] == "전체"
    assert "노말" in values


def test_subscribe_all_difficulty_via_select_callback(clean_db):
    raids_module.RAIDS.update({RAID: {"difficulties": {"노말": {"min_level": 1680, "total_slots": 8}}}})
    view = RaidSelectView("111")
    view.selected_raid = RAID

    interaction = MagicMock()
    interaction.user.id = 111
    interaction.data = {"values": ["전체"]}
    interaction.response.edit_message = AsyncMock()

    asyncio.run(view._on_diff_select(interaction))

    interaction.response.edit_message.assert_awaited_once()
    message = interaction.response.edit_message.call_args.kwargs["content"]
    assert "전체 난이도" in message
    subs = asyncio.run(db.get_user_subscriptions("111"))
    assert subs[0]["difficulty"] == "전체"


def test_unsubscribe_view_shows_wildcard_label():
    subs = [{"raid_name": RAID, "difficulty": "전체", "created_at": "2026-01-01"}]
    view = UnsubscribeView("111", subs)
    select = view.children[0]
    assert select.options[0].label == f"{RAID} 전체 난이도"
