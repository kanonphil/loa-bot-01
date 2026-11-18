"""전투력 추이(character_cp_history) — 동기화 시 일별 upsert, 조회 엔드포인트, 랭킹 cp_growth_7d."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import bot.api.lostark as loa
import bot.data.raids as raids_module
import bot.database.manager as db
from bot.services import expedition

WEB = {"X-Webapp-Key": "test-webapp-key"}
ME = "111"
OTHER = "222"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(ME, "key-me"))
    key_id = asyncio.run(db.add_user_api_key(ME, "본캐", "key-me"))
    asyncio.run(db.add_character(ME, "본캐", api_key_id=key_id))
    asyncio.run(db.update_character_cache(ME, "본캐", 1700, "바드"))
    asyncio.run(db.set_user_api_key(OTHER, "key-other"))
    from bot.api.server import app

    return TestClient(app)


def _today():
    return datetime.now(db.KST).date()


def _rows():
    con = sqlite3.connect(db.DB_PATH)
    rows = con.execute("SELECT character_name, date, combat_power, item_level FROM character_cp_history ORDER BY date").fetchall()
    con.close()
    return rows


def test_cp_write_upserts_one_row_per_day(client):
    asyncio.run(db.update_character_combat_power(ME, "본캐", 3000.5))
    asyncio.run(db.update_character_cache(ME, "본캐", 1705, "바드"))
    asyncio.run(db.update_character_combat_power(ME, "본캐", 3100.25))
    assert _rows() == [("본캐", _today().isoformat(), 3100.25, 1705.0)]
    # 등록 안 된 캐릭터는 기록하지 않는다
    asyncio.run(db.update_character_combat_power(ME, "남의캐릭", 9999))
    assert len(_rows()) == 1


def test_manual_sync_writes_history(client, monkeypatch):
    async def fake_siblings(key, name):
        return [{"CharacterName": "본캐", "ItemAvgLevel": "1,710.00", "CharacterClassName": "바드"}]

    async def fake_cp(key, name):
        return 3333.33

    monkeypatch.setattr(loa, "get_siblings", fake_siblings)
    monkeypatch.setattr(loa, "get_combat_power", fake_cp)
    asyncio.run(expedition.sync_characters_for_discord_id(ME))
    assert _rows() == [("본캐", _today().isoformat(), 3333.33, 1710.0)]


def test_daily_sync_writes_history(client, monkeypatch):
    async def fake_siblings(key, name):
        return [{"CharacterName": "본캐", "ItemAvgLevel": "1,712.50", "CharacterClassName": "바드"}]

    async def fake_cp(key, name):
        return 3400.0

    async def no_sleep(*_a):
        return None

    monkeypatch.setattr(loa, "get_siblings", fake_siblings)
    monkeypatch.setattr(loa, "get_combat_power", fake_cp)
    monkeypatch.setattr(expedition.asyncio, "sleep", no_sleep)
    asyncio.run(expedition.sync_all_accounts_daily())
    assert _rows() == [("본캐", _today().isoformat(), 3400.0, 1712.5)]


def _insert(name, days_ago, cp, il=1700.0):
    con = sqlite3.connect(db.DB_PATH)
    con.execute(
        "INSERT OR REPLACE INTO character_cp_history VALUES (?, ?, ?, ?)",
        (name, (_today() - timedelta(days=days_ago)).isoformat(), cp, il),
    )
    con.commit()
    con.close()


def test_history_endpoint(client):
    _insert("본캐", 100, 1000)
    _insert("본캐", 10, 2000)
    _insert("본캐", 0, 2500, 1710)
    resp = client.get("/api/internal/characters/본캐/history", params={"discord_id": OTHER}, headers=WEB)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["combat_power"] for i in items] == [2000, 2500]  # 기본 90일
    assert set(items[0]) == {"date", "combat_power", "item_level"}
    resp = client.get("/api/internal/characters/본캐/history", params={"discord_id": ME, "days": 365}, headers=WEB)
    assert len(resp.json()["items"]) == 3
    # 미등록 유저는 거부
    assert client.get("/api/internal/characters/본캐/history", params={"discord_id": "999"}, headers=WEB).status_code == 403


def test_ranking_cp_growth_7d(client):
    asyncio.run(db.add_character(ME, "부캐"))
    asyncio.run(db.update_character_cache(ME, "부캐", 1650, "워로드"))
    asyncio.run(db.update_character_combat_power(ME, "본캐", 3000))   # 오늘 기록도 생긴다
    asyncio.run(db.update_character_combat_power(ME, "부캐", 2000))
    _insert("본캐", 9, 2500)
    _insert("본캐", 7, 2750.5)   # 7일 전 이전 마지막 기록이 기준
    _insert("본캐", 3, 2900)
    _insert("부캐", 3, 1900)     # 7일 넘은 기록이 없음 → null
    resp = client.get("/api/internal/ranking", params={"metric": "combat_power"}, headers=WEB).json()
    by = {e["character_name"]: e for e in resp["entries"]}
    assert by["본캐"]["cp_growth_7d"] == 249.5
    assert by["부캐"]["cp_growth_7d"] is None
    for metric in ("item_level", "weekly_clears"):
        entries = client.get("/api/internal/ranking", params={"metric": metric}, headers=WEB).json()["entries"]
        assert all("cp_growth_7d" in e for e in entries)
