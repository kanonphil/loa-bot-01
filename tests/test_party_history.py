"""파티 완료/취소 이력 보관(party_history) 검증.

기존에는 주간 리셋 때 클리어된 파티가 parties 테이블에서 완전히 purge돼,
한 주만 지나면 캘린더/이력 조회에서 흔적도 없이 사라지는 문제가 있었다
(사용자가 "지난달 기록이 하나도 없다"고 지적한 바로 그 버그). 이제 purge_party가
지우기 직전에 party_history에 스냅샷을 남기므로, 지난 기록도 계속 조회 가능해야 한다.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import asyncio
import json

import pytest

import bot.database.manager as db

GUILD_ID = "1"
LEADER_ID = "111"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    asyncio.run(db.init_db())
    return path


async def _make_party(message_id: str, **overrides) -> None:
    params = dict(
        message_id=message_id, channel_id="555", guild_id=GUILD_ID, leader_id=LEADER_ID,
        raid_name="카멘", difficulty="노말", proficiency="숙련",
        scheduled_time="05/10 20:00", scheduled_datetime="2026-05-10T20:00:00+09:00",
        total_slots=8, min_level=1620,
    )
    params.update(overrides)
    await db.create_party(**params)


def test_purge_archives_cleared_party_with_slot_snapshot(db_path):
    async def run():
        await _make_party("p1")
        await db.auto_assign_slot("p1", LEADER_ID, "워로드캐릭", "워로드", "dps", 8)
        await db.disband_party("p1")  # 클리어 처리
        await db.purge_party("p1")  # 주간 리셋 때 발생하는 purge — status override 없음

        assert await db.get_party("p1") is None  # 살아있는 테이블에서는 사라져야 함

        async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
            conn.row_factory = __import__("aiosqlite").Row
            cur = await conn.execute("SELECT * FROM party_history WHERE message_id='p1'")
            row = dict(await cur.fetchone())

        assert row["status"] == "disbanded"  # override 없으면 기존 status 그대로 보관
        assert row["slot_count"] == 1
        slots = json.loads(row["slots_json"])
        assert slots[0]["character_name"] == "워로드캐릭"

    asyncio.run(run())


def test_purge_with_archived_status_override_records_cancelled(db_path):
    async def run():
        await _make_party("p2")  # status='recruiting'인 채로 바로 취소
        await db.purge_party("p2", archived_status="cancelled")

        async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
            conn.row_factory = __import__("aiosqlite").Row
            cur = await conn.execute("SELECT status FROM party_history WHERE message_id='p2'")
            row = dict(await cur.fetchone())

        assert row["status"] == "cancelled"

    asyncio.run(run())


def test_get_calendar_parties_includes_purged_history_across_month_boundary(db_path):
    async def run():
        await _make_party(
            "old-cleared", scheduled_time="06/05 20:00", scheduled_datetime="2026-06-05T20:00:00+09:00",
        )
        await db.disband_party("old-cleared")
        await db.purge_party("old-cleared")  # 지난달 클리어 파티가 이번 주 리셋으로 이미 purge된 상황 재현

        result = await db.get_calendar_parties(
            GUILD_ID, "2026-06-01T00:00:00", "2026-07-01T00:00:00"
        )
        ids = {p["message_id"] for p in result}
        assert "old-cleared" in ids

    asyncio.run(run())


def test_get_disbanded_parties_includes_purged_history(db_path):
    """관리자 앱의 '완료 이력' 조회(get_disbanded_parties)도 같은 문제를 겪고 있었다 —
    이제는 parties와 party_history를 합쳐서 봐야 한다."""
    async def run():
        await _make_party("cleared-live")
        await db.disband_party("cleared-live")  # 아직 purge되지 않은 이번 주 클리어 파티

        await _make_party("cleared-archived")
        await db.disband_party("cleared-archived")
        await db.purge_party("cleared-archived")  # 지난주에 클리어되고 이미 purge된 파티

        await _make_party("still-cancelled")
        await db.purge_party("still-cancelled", archived_status="cancelled")

        result = await db.get_disbanded_parties(GUILD_ID)
        ids = {p["message_id"] for p in result}

        assert "cleared-live" in ids
        assert "cleared-archived" in ids
        assert "still-cancelled" not in ids  # 취소는 '완료 이력'이 아니므로 제외

    asyncio.run(run())
