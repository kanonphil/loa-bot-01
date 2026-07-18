"""회귀 테스트: 초대(예약 슬롯) DB 기준 만료 처리.

InviteResponseView의 1시간 timeout은 discord.py View 인스턴스(메모리)에만 있어서
봇이 재시작되면 사라지고, party_invites 행이 영구히 남아 슬롯 하나가 계속
"예약중"으로 막힌다. bot.database.manager.get_expired_invites가 invited_at 기준으로
오래된 초대를 찾아 party_notification_task가 주기적으로 정리할 수 있게 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import aiosqlite
import pytest

import bot.database.manager as db


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


async def _insert_invite_with_age(message_id: str, discord_id: str, slot_number: int, hours_ago: float) -> None:
    """party_invites에 invited_at을 원하는 과거 시점으로 직접 심어 만료 시나리오를 재현."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO party_invites (message_id, discord_id, slot_number, invited_at) "
            "VALUES (?, ?, ?, datetime('now', ?))",
            (message_id, discord_id, slot_number, f"-{hours_ago} hours"),
        )
        await conn.commit()


def test_get_expired_invites_only_returns_old_entries(clean_db):
    asyncio.run(_insert_invite_with_age("700", "111", 1, hours_ago=2))   # 만료 대상
    asyncio.run(_insert_invite_with_age("700", "222", 2, hours_ago=0.1))  # 아직 안 지남

    expired = asyncio.run(db.get_expired_invites(hours=1))
    ids = {(e["message_id"], e["discord_id"]) for e in expired}
    assert ("700", "111") in ids
    assert ("700", "222") not in ids


def test_get_expired_invites_empty_when_nothing_old(clean_db):
    asyncio.run(_insert_invite_with_age("700", "111", 1, hours_ago=0.01))
    assert asyncio.run(db.get_expired_invites(hours=1)) == []


def test_expired_invite_cleanup_frees_reserved_slot(clean_db):
    """get_expired_invites로 찾은 항목을 delete_invite로 정리하면 예약 슬롯이 실제로
    풀려야 한다 — party_notification_task가 수행하는 정리 흐름과 동일하게 검증."""
    asyncio.run(_insert_invite_with_age("700", "111", 3, hours_ago=5))

    expired = asyncio.run(db.get_expired_invites(hours=1))
    assert len(expired) == 1
    for invite in expired:
        asyncio.run(db.delete_invite(invite["message_id"], invite["discord_id"]))

    reserved = asyncio.run(db.get_reserved_slots("700"))
    assert reserved == {}
