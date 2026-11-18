"""2026-11 봇 감사 결함 회귀 테스트(DB/코어 계층).

- 기한 지난 공대는 'expired'로 남고 클리어로 집계되지 않으며, 다음 주간 리셋까지 보관된다.
- 클리어는 같은 레이드 다른 난이도 체크를 대체하고, 되돌리기는 그 클리어가 만든 기록만 지운다.
- party_group 범위 검증, 유저 삭제 시 공대 상태 정리, 익스트림 원정대 주 1회 범위,
  초대 이중 수락, 같은 API 키 중복 등록, 키 삭제 후 재등록 시 캐릭터 재연결.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.data.raids import KST
from bot.ui import views

LEADER = "111"
MEMBER = "222"


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    yield
    asyncio.run(raids_module.reload())


def _future(hours: float = 48) -> str:
    return (datetime.now(KST) + timedelta(hours=hours)).isoformat()


async def _party(mid: str, *, raid="종막", diff="하드", sdt=None, total=8, leader=LEADER, min_level=1700):
    await db.create_party(
        message_id=mid, channel_id=f"c{mid}", guild_id="1", leader_id=leader,
        raid_name=raid, difficulty=diff, proficiency="숙련", scheduled_time="일정",
        scheduled_datetime=sdt if sdt is not None else _future(), total_slots=total, min_level=min_level,
    )


def _sql(query: str, params=()):
    con = sqlite3.connect(db.DB_PATH)
    try:
        rows = con.execute(query, params).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


# ── 1. expired ────────────────────────────────────────────

def test_expired_party_is_kept_until_next_reset_and_not_a_clear(setup):
    async def run():
        last_week = (datetime.fromisoformat(db.get_week_start_iso()) - timedelta(days=2)).isoformat()
        await _party("p1", sdt=last_week)
        await db.auto_assign_slot("p1", LEADER, "캐릭", "워로드", "dps", 8)
        week_start = db.get_week_start_iso()

        stale = await db.get_prev_week_active_parties(week_start)
        assert [p["message_id"] for p in stale] == ["p1"]
        assert await db.expire_party("p1")
        party = await db.get_party("p1")
        assert party["status"] == "expired" and party["ended_at"]

        # 예전 버그: 일정 기준이라 30초 뒤 다음 주기에 바로 purge 대상이 됐다
        assert await db.get_prev_week_disbanded_parties(week_start) == []
        # 클리어 기록 없음 + 캘린더에도 클리어로 안 보임
        assert _sql("SELECT COUNT(*) FROM raid_completions")[0][0] == 0
        start = (datetime.fromisoformat(week_start) - timedelta(days=14)).isoformat()
        cal = await db.get_calendar_parties("1", start, _future(24 * 14))
        assert cal == []

        # 다음 주가 시작되면(끝난 시각이 그 주 시작 전) 정리 대상
        next_week = (datetime.fromisoformat(week_start) + timedelta(days=7)).isoformat()
        assert [p["message_id"] for p in await db.get_prev_week_disbanded_parties(next_week)] == ["p1"]
        await db.purge_party("p1")
        assert _sql("SELECT status FROM party_history WHERE message_id='p1'") == [("expired",)]
        history = await db.get_disbanded_parties("1")
        assert history == []  # 클리어 이력 목록에도 안 들어간다
    asyncio.run(run())


def test_expire_party_only_touches_active(setup):
    async def run():
        await _party("p1")
        await db.disband_party("p1", cleared=True)
        assert not await db.expire_party("p1")
        assert (await db.get_party("p1"))["status"] == "disbanded"
    asyncio.run(run())


def test_legacy_party_without_schedule_compares_created_at_as_datetime(setup):
    """created_at(UTC 'YYYY-MM-DD HH:MM:SS')과 KST ISO 주 시작을 문자열로 비교하면
    공백(0x20)이 'T'보다 작아서 같은 날 생성된 공대가 '지난주'로 잘못 잡혔다."""
    async def run():
        await _party("p1", sdt="")
        _sql("UPDATE parties SET scheduled_datetime=NULL, created_at='2026-05-13 01:00:00' WHERE message_id='p1'")
        # 2026-05-13(수) 01:00 UTC = 10:00 KST → 06:00 KST 주 시작 이후
        assert await db.get_prev_week_active_parties("2026-05-13T06:00:00+09:00") == []
        assert len(await db.get_prev_week_active_parties("2026-05-20T06:00:00+09:00")) == 1
    asyncio.run(run())


def test_overdue_parties_and_reset_on_reschedule(setup):
    async def run():
        past = (datetime.now(KST) - timedelta(hours=db.OVERDUE_NOTIFY_HOURS + 1)).isoformat()
        recent = (datetime.now(KST) - timedelta(hours=1)).isoformat()
        await _party("old", sdt=past)
        await _party("new", sdt=recent)
        now = datetime.now(KST)
        assert [p["message_id"] for p in await db.get_overdue_parties(now)] == ["old"]
        await db.mark_overdue_notified("old")
        assert await db.get_overdue_parties(now) == []
        await db.update_party_schedule("old", "일정", past)
        assert [p["message_id"] for p in await db.get_overdue_parties(now)] == ["old"]
        await db.disband_party("old", cleared=True)
        assert await db.get_overdue_parties(now) == []
    asyncio.run(run())


# ── 10. 클리어 / 되돌리기 ──────────────────────────────────

def test_clear_replaces_other_difficulty_and_revert_only_removes_its_own_rows(setup, monkeypatch):
    monkeypatch.setattr("config.ADMIN_DISCORD_IDS", {"999"})

    async def run():
        week = db.get_week_key_for_dt(_future())
        await db.add_completion(LEADER, "본캐", "종막", "노말", week)          # 수동 노말 체크
        await db.add_completion(MEMBER, "부캐", "종막", "하드", week)          # 이미 하드(다른 공대)
        await _party("p1")
        await db.auto_assign_slot("p1", LEADER, "본캐", "워로드", "dps", 8)
        await db.auto_assign_slot("p1", MEMBER, "부캐", "버서커", "dps", 8)

        result = await views._clear_party_core(None, "p1", LEADER)
        assert result["success"] and result["cleared_count"] == 1  # 부캐는 이미 있던 행
        rows = _sql("SELECT discord_id, difficulty FROM raid_completions ORDER BY discord_id")
        assert rows == [(LEADER, "하드"), (MEMBER, "하드")]  # 노말+하드 이중 집계 없음

        revert = await views._admin_revert_clear_core(None, "p1", "999")
        assert revert["success"]
        # 이 클리어가 새로 만든 본캐 하드만 지워지고, 원래 있던 부캐 하드는 남는다
        assert _sql("SELECT discord_id, difficulty FROM raid_completions") == [(MEMBER, "하드")]
        assert (await db.get_party("p1"))["status"] in ("recruiting", "full")
    asyncio.run(run())


def test_revert_rejected_for_non_cleared_disbanded_and_expired(setup, monkeypatch):
    monkeypatch.setattr("config.ADMIN_DISCORD_IDS", {"999"})

    async def run():
        await _party("p1")
        await db.disband_party("p1")  # 파티원 전원 이탈 등 — 클리어 아님
        r1 = await views._admin_revert_clear_core(None, "p1", "999")
        assert not r1["success"]
        await _party("p2")
        await db.expire_party("p2")
        r2 = await views._admin_revert_clear_core(None, "p2", "999")
        assert not r2["success"]
    asyncio.run(run())


# ── 2. party_group 범위 ────────────────────────────────────

@pytest.mark.parametrize("group", [0, -1, 3])
def test_party_group_out_of_range_rejected(setup, group):
    async def run():
        await _party("p1")
        ok, slot, msg = await db.auto_assign_slot(
            "p1", MEMBER, "부캐", "워로드", "dps", 8, party_group=group, party_split=4,
        )
        assert not ok and slot == 0
        assert await db.get_party_slots("p1") == []
    asyncio.run(run())


def test_party_group_in_range_assigns_inside_group(setup):
    async def run():
        await _party("p1")
        ok, slot, _ = await db.auto_assign_slot("p1", MEMBER, "부캐", "워로드", "dps", 8, party_group=2, party_split=4)
        assert ok and 5 <= slot <= 8
    asyncio.run(run())


def test_concurrent_support_joins_only_one_succeeds(setup):
    async def run():
        await _party("p1", total=4)
        results = await asyncio.gather(*[
            db.auto_assign_slot("p1", f"u{i}", f"서폿{i}", "바드", "support", 4) for i in range(3)
        ])
        assert sum(1 for ok, _, _ in results if ok) == 1
    asyncio.run(run())


# ── 3. 유저 삭제 ───────────────────────────────────────────

def test_delete_user_leaves_parties_properly(setup):
    from bot.services.expedition import delete_user_and_leave_parties

    async def run():
        await _party("full4", total=4, leader=LEADER)
        for i, uid in enumerate([LEADER, MEMBER, "333", "444"]):
            await db.set_user_api_key(uid, f"k{i}")
            await db.auto_assign_slot("full4", uid, f"c{i}", "워로드", "dps", 4)
        assert (await db.get_party("full4"))["status"] == "full"
        await _party("ledonly", leader=LEADER)  # 참여 없이 파티장만 맡은 공대

        await delete_user_and_leave_parties(None, LEADER)

        party = await db.get_party("full4")
        assert party["status"] == "recruiting"           # 3/4가 됐으니 full 해제
        assert party["leader_id"] == MEMBER             # 다음 파티원에게 위임
        assert len(await db.get_party_slots("full4")) == 3
        assert (await db.get_party("ledonly"))["status"] == "disbanded"
        assert not await db.user_exists(LEADER)
    asyncio.run(run())


# ── 12. 익스트림 원정대 주 1회 ─────────────────────────────

def _setup_two_extreme_raids():
    asyncio.run(db.add_category("익스트림", 9))
    asyncio.run(db.update_category_extreme("익스트림", True))
    for name in ("익스A", "익스B"):
        asyncio.run(db.add_raid(name, name, "🔥", "익스트림"))
        asyncio.run(db.add_difficulty(name, "노말", 1600, 8, 4, 1, 0))
        asyncio.run(db.set_raid_period(name, (datetime.now(KST) - timedelta(days=1)).isoformat(), None))
    asyncio.run(raids_module.reload())


def test_extreme_clear_of_one_raid_blocks_join_of_another(setup):
    _setup_two_extreme_raids()

    async def run():
        await db.set_user_api_key(MEMBER, "k")
        await db.add_character(MEMBER, "부캐")
        await db.update_character_cache(MEMBER, "부캐", 1700, "워로드")
        sdt = (datetime.now(KST) + timedelta(minutes=30)).isoformat()
        await _party("pb", raid="익스B", diff="노말", sdt=sdt, leader="999")
        await db.set_extreme_completion(MEMBER, "익스A", "노말", "부캐", db.get_week_key_for_dt(sdt))
        result = await db.get_party_join_eligibility("pb", MEMBER)
        assert not result["can_join"] and "클리어" in result["reason"]
    asyncio.run(run())


def test_extreme_block_applies_to_guest(setup):
    _setup_two_extreme_raids()

    async def run():
        sdt = (datetime.now(KST) + timedelta(minutes=30)).isoformat()
        await _party("pa", raid="익스A", diff="노말", sdt=sdt, leader="999")
        await _party("pb", raid="익스B", diff="노말", sdt=sdt, leader="999")
        await db.auto_assign_slot("pa", "guest1", "게스트캐", "워로드", "dps", 8)
        reason = await db.get_extreme_join_block_reason("guest1", await db.get_party("pb"))
        assert reason and "참여 중" in reason
        # 자기 자신이 있는 공대는 "다른 공대"로 세지 않는다
        assert await db.get_extreme_join_block_reason("guest1", await db.get_party("pa")) is None
    asyncio.run(run())


# ── 11. 마감 공대 초대 수락 ────────────────────────────────

def test_invite_to_closed_party_can_be_accepted(setup):
    async def run():
        await db.set_user_api_key(MEMBER, "k")
        await db.add_character(MEMBER, "부캐")
        await db.update_character_cache(MEMBER, "부캐", 1740, "워로드")
        await _party("p1")
        await db.close_party("p1")
        await db.create_invite("p1", MEMBER, 3)
        # 초대 없는 일반 참여는 여전히 마감으로 거부
        assert not (await db.get_party_join_eligibility("p1", "333"))["can_join"]
        result = await views._accept_invite_core(None, "p1", MEMBER, "부캐", "dps")
        assert result["success"], result
        slots = await db.get_party_slots("p1")
        assert [(s["discord_id"], s["slot_number"]) for s in slots] == [(MEMBER, 3)]
        assert (await db.get_party("p1"))["status"] == "closed"
    asyncio.run(run())


def test_double_invite_accept_does_not_raise(setup):
    async def run():
        await _party("p1")
        await db.create_invite("p1", MEMBER, 2)
        r = await asyncio.gather(
            db.assign_invite_slot("p1", MEMBER, "부캐", "워로드", "dps"),
            db.assign_invite_slot("p1", MEMBER, "부캐", "워로드", "dps"),
        )
        assert sorted(ok for ok, _ in r) == [False, True]
    asyncio.run(run())


# ── 17/18. API 키 중복 / 재연결 ────────────────────────────

def test_same_api_key_cannot_be_registered_twice(setup):
    async def run():
        assert await db.add_user_api_key_unique(LEADER, "본캐", "same-key") is not None
        assert await db.add_user_api_key_unique(LEADER, "본캐2", "same-key") is None
        assert await db.add_user_api_key_unique(MEMBER, "남", "same-key") is None
        assert await db.api_key_already_registered("same-key")
        assert not await db.api_key_already_registered("other-key")
    asyncio.run(run())


def test_reregistering_key_relinks_unlinked_characters(setup, monkeypatch):
    from bot.services import expedition

    async def fake_siblings(key, name):
        return [{"CharacterName": "본캐"}, {"CharacterName": "부캐"}]

    monkeypatch.setattr(expedition.loa, "get_siblings", fake_siblings)
    monkeypatch.setattr(expedition.config, "REQUIRED_GUILD_NAME", "")

    async def run():
        key_id = await db.add_user_api_key(LEADER, "본캐", "old-key")
        await db.add_character(LEADER, "본캐", api_key_id=key_id)
        await db.add_character(LEADER, "부캐", api_key_id=key_id)
        await db.remove_user_api_key(LEADER, key_id)
        assert await db.get_character_api_key_id(LEADER, "본캐") is None

        ok, _msg, _sib, new_id = await expedition.verify_and_register_api_key(LEADER, "new-key", "본캐")
        assert ok
        assert await db.get_characters_by_api_key_id(new_id) == ["본캐", "부캐"]

        ok2, msg2, _, _ = await expedition.verify_and_register_api_key(LEADER, "new-key", "본캐")
        assert not ok2 and "이미 등록된" in msg2
    asyncio.run(run())


# ── 16. naive 운영 기간 ────────────────────────────────────

def test_naive_period_values_do_not_raise():
    raid_info = {"is_extreme": True, "available_from": "2026-01-01T06:00:00", "available_until": "2099-01-01T06:00:00"}
    dt = datetime.now(KST) + timedelta(days=1)
    assert views.validate_party_schedule(dt, raid_info) is None
    assert views.validate_party_schedule(datetime(2025, 6, 1, tzinfo=KST), {**raid_info, "available_from": None}) is not None


def test_normalize_period():
    start, end, err = raids_module.normalize_period("2026-09-01T06:00:00", "")
    assert err is None and start == "2026-09-01T06:00:00+09:00" and end is None
    assert raids_module.normalize_period("내일", None)[2]
    assert raids_module.normalize_period("2026-09-02T06:00:00+09:00", "2026-09-01T06:00:00+09:00")[2]


# ── 19. WAL / 인덱스 ──────────────────────────────────────

def test_wal_mode_and_channel_index(setup):
    assert _sql("PRAGMA journal_mode")[0][0].lower() == "wal"
    names = {r[0] for r in _sql("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_parties_channel" in names


def test_init_db_is_idempotent_with_new_columns(setup):
    asyncio.run(db.init_db())
    cols = {r[1] for r in _sql("PRAGMA table_info(parties)")}
    assert {"ended_at", "cleared_at", "overdue_notified"} <= cols


def test_batched_completions_and_selections(setup):
    async def run():
        week = db.get_week_key()
        await db.add_completion(LEADER, "A", "종막", "노말", week)
        await db.add_completion(LEADER, "B", "세르카", "하드", week)
        await db.set_selected_raids(LEADER, "A", ["종막"])
        await db.set_selected_raids(LEADER, "C", [])
        comp = await db.get_week_completions_by_character(LEADER, week)
        assert comp == {"A": {"종막_노말"}, "B": {"세르카_하드"}}
        sel = await db.get_all_selected_raids(LEADER)
        assert sel == {"A": ["종막"], "C": []}
    asyncio.run(run())
