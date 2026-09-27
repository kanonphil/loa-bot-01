"""레이드 관리 "수정" — 약칭/아이콘/난이도 수치 변경, 이름 변경의 참조 테이블 연쇄 갱신,
카테고리 삭제 가드(소속 레이드 검사)."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
import config

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "111"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})
    asyncio.run(db.init_db())
    asyncio.run(db.add_category("카제로스", 0))
    asyncio.run(db.add_raid("카양겔", "카양", "⚔️", "카제로스"))
    asyncio.run(db.add_difficulty("카양겔", "노말", 1600, 8, 4, 2, 0))
    asyncio.run(db.add_difficulty("카양겔", "하드", 1620, 8, 4, 2, 1))
    asyncio.run(raids_module.reload())
    from bot.api.server import app

    return TestClient(app)


def _post(client, path, **body):
    return client.post(f"/api/internal/admin/{path}", json={"discord_id": ADMIN_ID, **body}, headers=HEADERS).json()


def _count(table, where, params):
    con = sqlite3.connect(db.DB_PATH)
    n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
    con.close()
    return n


def _seed_references(raid="카양겔", diff="노말"):
    """레이드 이름을 문자열로 들고 있는 테이블 전부에 한 줄씩."""
    asyncio.run(db.create_party(
        message_id="p1", channel_id="c1", guild_id="g1", leader_id="222",
        raid_name=raid, difficulty=diff, proficiency="숙련",
        scheduled_time="05/20 20:00", scheduled_datetime="2099-05-20T20:00:00+09:00",
        total_slots=8, min_level=1600,
    ))
    asyncio.run(db.create_party(
        message_id="p2", channel_id="c2", guild_id="g1", leader_id="222",
        raid_name=raid, difficulty=diff, proficiency="숙련",
        scheduled_time="05/13 20:00", scheduled_datetime="2026-05-13T20:00:00+09:00",
        total_slots=8, min_level=1600,
    ))
    asyncio.run(db.auto_assign_slot("p2", "222", "리더", "워로드", "dps", 8))
    asyncio.run(db.disband_party("p2"))
    asyncio.run(db.purge_party("p2"))  # → party_history
    asyncio.run(db.add_completion("333", "발키리", raid, diff, "2026-05-13"))
    asyncio.run(db.subscribe_raid("333", raid, "전체"))
    asyncio.run(db.subscribe_raid("444", raid, diff))
    asyncio.run(db.set_selected_raids("333", "발키리", [raid]))
    asyncio.run(db.log_notification("333", raid, diff, "p1"))


# ── 필드 수정 ────────────────────────────────────────────

def test_update_raid_fields_reloads_cache(client):
    assert _post(client, "raids/update", name="카양겔", short_name="캉겔", icon="🔥") == {"success": True}
    assert raids_module.RAIDS["카양겔"]["short_name"] == "캉겔"
    assert raids_module.RAIDS["카양겔"]["icon"] == "🔥"
    assert _post(client, "raids/update", name="없음", short_name="x", icon="⚔️")["success"] is False
    assert _post(client, "raids/update", name="카양겔", short_name="  ", icon="⚔️")["success"] is False


def test_update_difficulty_numbers_and_validation(client):
    ok = _post(client, "difficulties/update", raid_name="카양겔", difficulty="노말",
               min_level=1650, total_slots=16, party_split=8, gates=3)
    assert ok == {"success": True}
    d = raids_module.RAIDS["카양겔"]["difficulties"]["노말"]
    assert (d["min_level"], d["total_slots"], d["party_split"], d["gates"]) == (1650, 16, 8, 3)

    bad_split = _post(client, "difficulties/update", raid_name="카양겔", difficulty="노말",
                      min_level=1650, total_slots=8, party_split=3, gates=2)
    assert bad_split["success"] is False and "분할" in bad_split["reason"]
    bad_level = _post(client, "difficulties/update", raid_name="카양겔", difficulty="노말",
                      min_level=0, total_slots=8, party_split=None, gates=2)
    assert bad_level["success"] is False
    missing = _post(client, "difficulties/update", raid_name="카양겔", difficulty="없음",
                    min_level=1650, total_slots=8, party_split=None, gates=2)
    assert missing["success"] is False


def test_add_difficulty_uses_same_validation(client):
    bad = _post(client, "difficulties/add", raid_name="카양겔", difficulty="익스",
                min_level=1700, total_slots=8, party_split=3, gates=1)
    assert bad["success"] is False and "분할" in bad["reason"]


# ── 이름 변경 연쇄 ────────────────────────────────────────

def test_rename_raid_cascades_every_referencing_table(client):
    _seed_references()
    refs = client.get("/api/internal/admin/raids/references",
                      params={"discord_id": ADMIN_ID, "name": "카양겔"}, headers=HEADERS).json()
    assert refs == {
        "parties_live": 1, "parties_all": 1, "party_history": 1, "raid_completions": 1,
        "raid_subscriptions": 2, "character_raid_selection": 1, "notification_logs": 1,
    }

    assert _post(client, "raids/rename", old_name="카양겔", new_name="카양겔 (리마스터)") == {"success": True}
    new = "카양겔 (리마스터)"
    for table in ("raid_difficulties", "raid_completions", "parties", "party_history",
                  "character_raid_selection", "raid_subscriptions", "notification_logs"):
        assert _count(table, "raid_name=?", ("카양겔",)) == 0, table
        assert _count(table, "raid_name=?", (new,)) >= 1, table
    assert _count("raid_difficulties", "raid_name=?", (new,)) == 2
    assert new in raids_module.RAIDS and "카양겔" not in raids_module.RAIDS
    assert raids_module.RAIDS[new]["category"] == "카제로스"
    assert set(raids_module.RAIDS[new]["difficulties"]) == {"노말", "하드"}
    # 살아있는 파티 상세도 새 이름으로 읽힌다
    assert asyncio.run(db.get_party("p1"))["raid_name"] == new


def test_rename_raid_rejects_duplicate_empty_unknown_and_unchanged(client):
    asyncio.run(db.add_raid("종막", "종막", "⚔️", "카제로스"))
    asyncio.run(raids_module.reload())
    assert _post(client, "raids/rename", old_name="카양겔", new_name="종막")["success"] is False
    assert _post(client, "raids/rename", old_name="카양겔", new_name="   ")["success"] is False
    assert _post(client, "raids/rename", old_name="없는레이드", new_name="x")["success"] is False
    assert _post(client, "raids/rename", old_name="카양겔", new_name="카양겔") == {"success": True, "unchanged": True}
    assert "카양겔" in raids_module.RAIDS


def test_rename_raid_requires_admin(client):
    resp = client.post("/api/internal/admin/raids/rename",
                       json={"discord_id": "999", "old_name": "카양겔", "new_name": "x"}, headers=HEADERS).json()
    assert resp["success"] is False
    assert client.get("/api/internal/admin/raids/references",
                      params={"discord_id": "999", "name": "카양겔"}, headers=HEADERS).status_code == 403


def test_rename_category_cascades_raids(client):
    assert _post(client, "categories/rename", old_name="카제로스", new_name="카제로스 군단장") == {"success": True}
    assert raids_module.RAIDS["카양겔"]["category"] == "카제로스 군단장"
    assert "카제로스 군단장" in {c["name"] for c in asyncio.run(db.get_categories())}
    dup = _post(client, "categories/rename", old_name="카제로스 군단장", new_name="어비스")  # init_db 기본 카테고리
    assert dup["success"] is False


def test_rename_difficulty_cascades_and_keeps_wildcard_subscription(client):
    _seed_references(diff="노말")
    assert _post(client, "difficulties/rename", raid_name="카양겔", old_difficulty="노말", new_difficulty="일반") == {"success": True}
    for table in ("raid_difficulties", "raid_completions", "parties", "party_history", "notification_logs"):
        assert _count(table, "raid_name=? AND difficulty=?", ("카양겔", "노말")) == 0, table
        assert _count(table, "raid_name=? AND difficulty=?", ("카양겔", "일반")) == 1, table
    # '전체' 와일드카드 구독은 그대로, 난이도 지정 구독은 새 이름으로
    assert _count("raid_subscriptions", "raid_name=? AND difficulty=?", ("카양겔", "전체")) == 1
    assert _count("raid_subscriptions", "raid_name=? AND difficulty=?", ("카양겔", "일반")) == 1
    assert set(raids_module.RAIDS["카양겔"]["difficulties"]) == {"일반", "하드"}
    dup = _post(client, "difficulties/rename", raid_name="카양겔", old_difficulty="일반", new_difficulty="하드")
    assert dup["success"] is False


# ── 카테고리 삭제 가드 ────────────────────────────────────

def test_delete_category_with_raids_is_rejected(client):
    resp = _post(client, "categories/delete", name="카제로스")
    assert resp["success"] is False and "소속 레이드가" in resp["reason"]  # init_db 기본 레이드도 카제로스 소속
    assert "카제로스" in {c["name"] for c in asyncio.run(db.get_categories())}
    assert "카양겔" in raids_module.RAIDS
