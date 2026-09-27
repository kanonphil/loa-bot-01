"""익스트림 레이드 = 원정대(discord_id) 단위 주 1회 — DB 규칙, 내부 API, 참여 차단, 디스코드 임베드."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.data.raids import KST, active_extreme_raids, get_applicable_raids, is_extreme_available

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ME = "111"
WEEK = db.get_week_key()


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    con = sqlite3.connect(db.DB_PATH)
    for t in ("raid_difficulties", "raids_data", "raid_categories"):
        con.execute(f"DELETE FROM {t}")
    con.commit(); con.close()

    asyncio.run(db.add_category("카제로스", 0))
    asyncio.run(db.add_raid("종막", "종막", "⚔️", "카제로스"))
    asyncio.run(db.add_difficulty("종막", "노말", 1700, 8, 4, 2, 0))
    asyncio.run(db.add_category("익스트림", 1))
    asyncio.run(db.update_category_extreme("익스트림", True))
    asyncio.run(db.add_raid("카멘익스", "익스", "🔥", "익스트림"))
    asyncio.run(db.add_difficulty("카멘익스", "노말", 1700, 8, 4, 1, 0))
    asyncio.run(db.add_difficulty("카멘익스", "하드", 1730, 8, 4, 1, 1))
    asyncio.run(db.set_raid_period(
        "카멘익스", (datetime.now(KST) - timedelta(days=1)).isoformat(),
        (datetime.now(KST) + timedelta(days=10)).isoformat(),
    ))
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(ME, "dummy-key"))
    for name, cls, lv in (("발키리", "홀리나이트", 1735.0), ("워로드부캐", "워로드", 1722.0)):
        asyncio.run(db.add_character(ME, name))
        asyncio.run(db.update_character_cache(ME, name, lv, cls))
    yield
    asyncio.run(raids_module.reload())


@pytest.fixture()
def client(setup):
    from bot.api.server import app

    return TestClient(app)


def _rows(discord_id=ME):
    con = sqlite3.connect(db.DB_PATH)
    rows = con.execute(
        "SELECT character_name, raid_name, difficulty FROM raid_completions WHERE discord_id=? ORDER BY character_name",
        (discord_id,),
    ).fetchall()
    con.close()
    return rows


# ── raids 헬퍼 ────────────────────────────────────────────

def test_applicable_raids_excludes_extreme_by_default(setup):
    names = {r for r, _, _ in get_applicable_raids(1800)}
    assert names == {"종막"}
    with_extreme = {r for r, _, _ in get_applicable_raids(1800, include_extreme=True)}
    assert with_extreme == {"종막", "카멘익스"}


def test_active_extreme_raids_respects_period(setup):
    assert [n for n, _ in active_extreme_raids()] == ["카멘익스"]
    future = {**raids_module.RAIDS["카멘익스"], "available_from": (datetime.now(KST) + timedelta(days=1)).isoformat()}
    assert is_extreme_available(future) is False
    naive_past = {**raids_module.RAIDS["카멘익스"], "available_until": "2020-01-01T00:00:00"}  # naive도 TypeError 없이
    assert is_extreme_available(naive_past) is False
    assert is_extreme_available({**raids_module.RAIDS["카멘익스"], "is_active": False}) is False


# ── DB 규칙 ──────────────────────────────────────────────

def test_set_extreme_completion_keeps_one_row_per_expedition(setup):
    asyncio.run(db.set_extreme_completion(ME, "카멘익스", "노말", "발키리"))
    asyncio.run(db.set_extreme_completion(ME, "카멘익스", "하드", "워로드부캐"))
    assert _rows() == [("워로드부캐", "카멘익스", "하드")]
    status = asyncio.run(db.get_expedition_extreme_status(ME))
    assert status == {"카멘익스": {"difficulty": "하드", "character_name": "워로드부캐"}}
    assert asyncio.run(db.clear_extreme_completion(ME, "카멘익스")) == 1
    assert _rows() == []
    assert asyncio.run(db.get_expedition_extreme_status(ME)) == {}


def test_normal_raid_still_allows_multiple_characters(setup):
    asyncio.run(db.add_completion(ME, "발키리", "종막", "노말", WEEK))
    asyncio.run(db.add_completion(ME, "워로드부캐", "종막", "노말", WEEK))
    assert len(_rows()) == 2
    assert asyncio.run(db.get_expedition_extreme_status(ME)) == {}  # 일반 레이드는 익스트림 상태에 안 잡힘


def test_party_clear_replaces_manual_extreme_check(setup):
    asyncio.run(db.set_extreme_completion(ME, "카멘익스", "노말", "워로드부캐"))
    asyncio.run(db.create_party(
        message_id="x1", channel_id="c", guild_id="g", leader_id=ME,
        raid_name="카멘익스", difficulty="하드", proficiency="숙련",
        scheduled_time="now", scheduled_datetime=datetime.now(KST).isoformat(),
        total_slots=8, min_level=1730,
    ))
    asyncio.run(db.auto_assign_slot("x1", ME, "발키리", "홀리나이트", "support", 8))
    asyncio.run(db.complete_raid_for_party("x1"))
    assert _rows() == [("발키리", "카멘익스", "하드")]


# ── 참여 차단 ─────────────────────────────────────────────

def _extreme_party(message_id="e1", start=None):
    start = start or (datetime.now(KST) + timedelta(hours=3))
    asyncio.run(db.create_party(
        message_id=message_id, channel_id="c", guild_id="g", leader_id="999",
        raid_name="카멘익스", difficulty="노말", proficiency="숙련",
        scheduled_time="soon", scheduled_datetime=start.isoformat(),
        total_slots=8, min_level=1700,
    ))


def test_cleared_extreme_blocks_join_switch_but_not_normal_raid(setup):
    _extreme_party("e1")
    assert asyncio.run(db.get_party_join_eligibility("e1", ME))["can_join"] is True
    asyncio.run(db.set_extreme_completion(ME, "카멘익스", "노말", "발키리"))
    result = asyncio.run(db.get_party_join_eligibility("e1", ME))
    assert result["can_join"] is False
    assert "발키리" in result["reason"] and "클리어" in result["reason"]

    # 일반 레이드 공대는 영향 없음
    asyncio.run(db.create_party(
        message_id="n1", channel_id="c", guild_id="g", leader_id="999",
        raid_name="종막", difficulty="노말", proficiency="숙련",
        scheduled_time="soon", scheduled_datetime=(datetime.now(KST) + timedelta(hours=3)).isoformat(),
        total_slots=8, min_level=1700,
    ))
    assert asyncio.run(db.get_party_join_eligibility("n1", ME))["can_join"] is True

    # 이미 참여 중인 익스트림 공대에서 캐릭터 교체도 막힘
    asyncio.run(db.clear_extreme_completion(ME, "카멘익스"))
    asyncio.run(db.auto_assign_slot("e1", ME, "워로드부캐", "워로드", "dps", 8))
    asyncio.run(db.set_extreme_completion(ME, "카멘익스", "노말", "워로드부캐"))
    switch = asyncio.run(db.get_party_switch_eligibility("e1", ME))
    assert switch["can_switch"] is False and "클리어" in switch["reason"]


def test_cleared_party_no_longer_lets_expedition_join_second_extreme_party(setup):
    """기존 구멍: 첫 익스트림 공대가 클리어(disbanded)되면 진행 중 공대 검사에서 빠져 재참여가 가능했다."""
    _extreme_party("e1", start=datetime.now(KST) + timedelta(hours=1))
    asyncio.run(db.auto_assign_slot("e1", ME, "발키리", "홀리나이트", "support", 8))
    asyncio.run(db.complete_raid_for_party("e1"))
    asyncio.run(db.disband_party("e1"))
    _extreme_party("e2", start=datetime.now(KST) + timedelta(hours=5))
    result = asyncio.run(db.get_party_join_eligibility("e2", ME))
    assert result["can_join"] is False and "발키리" in result["reason"]


# ── 내부 API ─────────────────────────────────────────────

def test_extreme_endpoints_and_progress(client):
    status = client.get("/api/internal/completions/extreme", params={"discord_id": ME}, headers=HEADERS).json()
    assert status["week_key"] == WEEK
    assert [(r["raid_name"], r["cleared"]) for r in status["raids"]] == [("카멘익스", False)]
    assert set(status["raids"][0]["difficulties"]) == {"노말", "하드"}

    progress = client.get("/api/internal/raid-progress", params={"discord_id": ME}, headers=HEADERS).json()
    assert progress["total"] == 2  # 캐릭터 2 × 종막 1 — 익스트림은 캐릭터 총합에서 제외
    assert progress["extreme"][0]["cleared"] is False

    bad = client.post("/api/internal/completions/extreme/set", headers=HEADERS,
                      json={"discord_id": ME, "raid_name": "종막", "difficulty": "노말", "character_name": "발키리"}).json()
    assert bad["success"] is False
    other = client.post("/api/internal/completions/extreme/set", headers=HEADERS,
                        json={"discord_id": ME, "raid_name": "카멘익스", "difficulty": "노말", "character_name": "남의캐릭"}).json()
    assert other["success"] is False and "본인" in other["reason"]

    ok = client.post("/api/internal/completions/extreme/set", headers=HEADERS,
                     json={"discord_id": ME, "raid_name": "카멘익스", "difficulty": "하드", "character_name": "발키리"}).json()
    assert ok == {"success": True, "character_name": "발키리", "difficulty": "하드"}
    progress = client.get("/api/internal/raid-progress", params={"discord_id": ME}, headers=HEADERS).json()
    assert progress["extreme"][0] == {**progress["extreme"][0], "cleared": True, "character_name": "발키리", "difficulty": "하드"}
    assert progress["total"] == 2

    cleared = client.post("/api/internal/completions/extreme/clear", headers=HEADERS,
                          json={"discord_id": ME, "raid_name": "카멘익스"}).json()
    assert cleared == {"success": True, "removed": 1}


# ── 디스코드 임베드 ───────────────────────────────────────

def test_checklist_embed_moves_extreme_to_expedition_field(setup):
    from bot.ui.embeds import raid_checklist_embed

    embed = raid_checklist_embed("발키리", 1735.0, set(), extreme_status=[
        {"raid_name": "카멘익스", "icon": "🔥", "cleared": True, "character_name": "워로드부캐",
         "difficulty": "하드", "available_until": None},
    ])
    fields = {f.name: f.value for f in embed.fields}
    assert "카멘익스" not in fields.get("◈ 카제로스", "")
    assert "◈ 익스트림" not in fields
    assert "워로드부캐" in fields["⚡ 익스트림 (원정대 주 1회)"]
    assert "1" in embed.description  # 종막 1개만 분모

    plain = raid_checklist_embed("발키리", 1735.0, set())
    assert all("익스트림" not in f.name for f in plain.fields)
