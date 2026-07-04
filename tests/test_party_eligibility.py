"""db.get_party_join_eligibility 검증 — Discord 참여 버튼과 웹 참여 API가 공유하는
단일 판단 로직이므로, 여기서 철저히 검증해둔다.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.database.manager as db
import bot.data.raids as raids_module


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())  # RAIDS/SUPPORT_CLASSES 캐시 채우기

    asyncio.run(db.set_user_api_key("111", "dummy-key"))
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1710.0, character_class="홀리나이트")
    )

    asyncio.run(
        db.create_party(
            message_id="p1", channel_id="c1", guild_id="g1", leader_id="222",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    yield
    asyncio.run(raids_module.reload())  # 다음 테스트 파일 오염 방지 (실제 DB 파일은 각자 tmp_path라 상관없지만 안전하게)


def test_qualifying_character_can_join(setup):
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is True
    names = [q["name"] for q in result["qualifying"]]
    assert names == ["발키리"]


def test_already_joined_cannot_join_again(setup):
    asyncio.run(db.auto_assign_slot("p1", "111", "발키리", "서포터", "support", 8))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is False
    assert "이미" in result["reason"]


def test_full_party_rejected(setup):
    asyncio.run(db.get_party("p1"))
    async def fill():
        for i in range(8):
            await db.auto_assign_slot("p1", str(1000 + i), f"딜러{i}", "워로드", "dps", 8)
    asyncio.run(fill())
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is False
    assert "꽉" in result["reason"]


def test_disbanded_party_rejected(setup):
    asyncio.run(db.disband_party("p1"))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is False


def test_closed_party_rejected(setup):
    asyncio.run(db.close_party("p1"))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is False
    assert "마감" in result["reason"]


def test_level_too_low_excluded(setup):
    asyncio.run(db.update_character_cache("111", "발키리", item_level=1650.0, character_class="홀리나이트"))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is True
    assert result["qualifying"] == []
    assert result["level_too_low"] == [{"name": "발키리", "level": 1650.0}]


def test_no_api_key_rejected(setup):
    asyncio.run(db.delete_user("111"))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is False
    assert "api등록" in result["reason"]


def test_gold_done_character_excluded(setup):
    week_key = db.get_week_key_for_dt("2026-05-20T20:00:00+09:00")
    asyncio.run(db.add_completion("111", "발키리", "아르모체(4막)", "노말", week_key))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is True
    assert result["qualifying"] == []
    assert result["gold_done"] == ["발키리"]


def test_already_in_other_party_same_raid_excluded(setup):
    asyncio.run(
        db.create_party(
            message_id="p2", channel_id="c2", guild_id="g1", leader_id="333",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("p2", "111", "발키리", "서포터", "support", 8))

    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert result["can_join"] is True
    assert result["qualifying"] == []
    assert result["in_other_party"] == ["발키리"]


def test_no_cache_character_reported_separately(setup):
    asyncio.run(db.add_character("111", "새캐릭"))
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    assert "새캐릭" in result["no_cache"]


def test_party_split_returned_from_raid_data(setup):
    result = asyncio.run(db.get_party_join_eligibility("p1", "111"))
    # seed_game_data: 아르모체(4막) 노말 difficulty의 party_split=4
    assert result["party_split"] == 4
    assert result["total_slots"] == 8
