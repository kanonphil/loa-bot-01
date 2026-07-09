"""bot/database/manager.py::get_party_slots의 is_guest 필드 검증.
/api등록(users 테이블)을 거치지 않은 discord_id로 채워진 슬롯만 게스트로 표시돼야 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db


@pytest.fixture()
def party_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key("111", "dummy-key"))  # /api등록 완료 → users 테이블에 존재

    asyncio.run(
        db.create_party(
            message_id="999", channel_id="555", guild_id="1", leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    # 111 = 정식 등록 유저, 222 = 게스트(초대로 참여, /api등록 이력 없음)
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "홀리나이트", "dps", 8))
    asyncio.run(db.auto_assign_slot("999", "222", "게스트캐릭", "워로드", "dps", 8))
    return "999"


def test_registered_member_slot_is_not_guest(party_setup):
    slots = asyncio.run(db.get_party_slots(party_setup))
    slot = next(s for s in slots if s["discord_id"] == "111")
    assert slot["is_guest"] is False


def test_unregistered_member_slot_is_guest(party_setup):
    slots = asyncio.run(db.get_party_slots(party_setup))
    slot = next(s for s in slots if s["discord_id"] == "222")
    assert slot["is_guest"] is True
