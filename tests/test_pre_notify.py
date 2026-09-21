"""사전 알림(N시간 전) — 스키마만 있던 기능의 실제 구현 검증: 설정 저장, 발송 대상 계산,
한 번만 보내기, 일정 변경 시 재발송."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from datetime import datetime, timedelta

import pytest

import bot.database.manager as db
from bot.bot import _format_remaining

KST = db.KST


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def _party(message_id: str, start: datetime, status: str = "recruiting"):
    asyncio.run(db.create_party(
        message_id=message_id, channel_id="700", guild_id="1", leader_id="111",
        raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
        scheduled_time=start.strftime("%m/%d %H:%M"), scheduled_datetime=start.isoformat(),
        total_slots=8, min_level=1700,
    ))
    asyncio.run(db.auto_assign_slot(message_id, "111", "리더캐릭", "워로드", "dps", 8))
    asyncio.run(db.auto_assign_slot(message_id, "222", "멤버캐릭", "바드", "support", 8))
    if status == "disbanded":
        asyncio.run(db.disband_party(message_id))


def test_pre_notify_hours_default_off_then_set(fresh_db):
    assert asyncio.run(db.get_pre_notify_hours("111")) == 0.0
    asyncio.run(db.set_pre_notify_hours("111", 2))
    assert asyncio.run(db.get_pre_notify_hours("111")) == 2.0
    asyncio.run(db.set_pre_notify_hours("111", 0))
    assert asyncio.run(db.get_pre_notify_hours("111")) == 0.0


def test_due_only_for_members_who_opted_in_and_within_window(fresh_db):
    now = datetime.now(KST).replace(microsecond=0)
    _party("soon", now + timedelta(minutes=50))       # 1시간 안
    _party("later", now + timedelta(hours=5))         # 아직 멀다
    _party("past", now - timedelta(minutes=5))        # 이미 시작
    asyncio.run(db.set_pre_notify_hours("111", 1))    # 111만 켬(1시간 전)

    due = asyncio.run(db.get_due_pre_notifications(now))
    assert [(d["message_id"], d["discord_id"]) for d in due] == [("soon", "111")]
    assert 49 <= due[0]["remaining_minutes"] <= 50


def test_due_sent_once_and_rearmed_after_reschedule(fresh_db):
    now = datetime.now(KST).replace(microsecond=0)
    _party("soon", now + timedelta(minutes=30))
    asyncio.run(db.set_pre_notify_hours("222", 1))

    assert len(asyncio.run(db.get_due_pre_notifications(now))) == 1
    asyncio.run(db.mark_pre_notified("soon", "222"))
    assert asyncio.run(db.get_due_pre_notifications(now)) == []

    # 일정 변경 → 사전 알림 기록이 비워져 새 시각 기준으로 다시 간다
    new_start = now + timedelta(minutes=40)
    asyncio.run(db.update_party_schedule("soon", new_start.strftime("%m/%d %H:%M"), new_start.isoformat()))
    assert [d["message_id"] for d in asyncio.run(db.get_due_pre_notifications(now))] == ["soon"]


def test_due_skips_disbanded_parties(fresh_db):
    now = datetime.now(KST).replace(microsecond=0)
    _party("done", now + timedelta(minutes=30), status="disbanded")
    asyncio.run(db.set_pre_notify_hours("111", 1))
    assert asyncio.run(db.get_due_pre_notifications(now)) == []


def test_format_remaining():
    assert _format_remaining(30) == "30분"
    assert _format_remaining(60) == "1시간"
    assert _format_remaining(90) == "1시간 30분"
    assert _format_remaining(0) == "1분"
