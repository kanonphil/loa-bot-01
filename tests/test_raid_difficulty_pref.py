"""주간 골드 — 난이도 clear_gold(관리자 입력)와 /raid-check-summary의 골드 합산."""
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

WEB = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "1"
ME = "111"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})
    asyncio.run(db.init_db())
    asyncio.run(db.add_category("골드테스트", 99))
    asyncio.run(db.add_raid("가토", "가토", "x", "골드테스트"))
    asyncio.run(db.add_raid("나비", "나비", "x", "골드테스트"))
    asyncio.run(db.add_difficulty("가토", "노말", 1600, 8, 4, 2, 0, 1000))
    asyncio.run(db.add_difficulty("가토", "하드", 1700, 8, 4, 2, 1, 2000))
    asyncio.run(db.add_difficulty("가토", "나메", 1750, 8, 4, 2, 2, 9000))  # 입장 불가 — 합산 제외
    asyncio.run(db.add_difficulty("나비", "노말", 1600, 4, None, 1, 0, 500))
    asyncio.run(db.add_difficulty("나비", "하드", 1700, 4, None, 1, 1, None))
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(ME, "dummy"))
    asyncio.run(db.add_character(ME, "본캐"))
    asyncio.run(db.update_character_cache(ME, "본캐", 1720, "바드"))
    asyncio.run(db.add_character(ME, "부캐"))
    asyncio.run(db.update_character_cache(ME, "부캐", 1650, "워로드"))
    from bot.api.server import app

    yield TestClient(app)
    asyncio.run(raids_module.reload())


def _summary(client):
    return client.get("/api/internal/raid-check-summary", params={"discord_id": ME}, headers=WEB).json()


def _pref(client, char, raid, diff, who=ME):
    return client.post("/api/internal/raid-difficulty-pref", headers=WEB, json={
        "discord_id": who, "character_name": char, "raid_name": raid, "difficulty": diff}).json()


def _prefs_of(data, char):
    c = next(c for c in data["characters"] if c["character_name"] == char)
    return {r["raid_name"]: r["preferred_difficulty"] for r in c["applicable_raids"]}


def test_pref_default_null_and_round_trip(client):
    assert set(_prefs_of(_summary(client), "본캐").values()) == {None}
    assert _pref(client, "본캐", "가토", "하드") == {"success": True, "difficulty": "하드"}
    p = _prefs_of(_summary(client), "본캐")
    assert p["가토"] == "하드" and p["나비"] is None
    assert _prefs_of(_summary(client), "부캐")["가토"] is None  # 캐릭터별 분리
    _pref(client, "본캐", "가토", "노말")  # 덮어쓰기
    assert _prefs_of(_summary(client), "본캐")["가토"] == "노말"


def test_pref_null_deletes(client):
    _pref(client, "본캐", "가토", "하드")
    assert _pref(client, "본캐", "가토", None) == {"success": True, "difficulty": None}
    assert _prefs_of(_summary(client), "본캐")["가토"] is None
    assert asyncio.run(db.get_difficulty_prefs(ME)) == {}


def test_pref_invalid_character(client):
    r = _pref(client, "없는캐", "가토", "노말")
    assert r["success"] is False and r["reason"]
    asyncio.run(db.set_user_api_key("222", "d"))
    asyncio.run(db.add_character("222", "남캐"))
    assert _pref(client, "남캐", "가토", "노말")["success"] is False  # 남의 캐릭터


def test_pref_invalid_difficulty_or_raid(client):
    assert _pref(client, "부캐", "가토", "나메")["success"] is False   # 1650은 나메 불가
    assert _pref(client, "부캐", "가토", "하드")["success"] is False   # 하드 1700 필요
    assert _pref(client, "본캐", "가토", "없음")["success"] is False
    assert _pref(client, "본캐", "없는레이드", "노말")["success"] is False
    assert asyncio.run(db.get_difficulty_prefs(ME)) == {}


def test_stale_pref_is_null(client):
    _pref(client, "본캐", "가토", "하드")
    asyncio.run(db.update_character_cache(ME, "본캐", 1650, "바드"))  # 레벨 하락 -> 하드 불가
    assert _prefs_of(_summary(client), "본캐")["가토"] is None
    asyncio.run(db.update_character_cache(ME, "본캐", 1720, "바드"))
    assert _prefs_of(_summary(client), "본캐")["가토"] == "하드"


def test_pref_fetched_in_one_query(client, monkeypatch):
    _pref(client, "본캐", "가토", "하드")
    calls = []
    orig = db.get_difficulty_prefs

    async def spy(discord_id):
        calls.append(discord_id)
        return await orig(discord_id)

    monkeypatch.setattr(db, "get_difficulty_prefs", spy)
    _summary(client)
    assert calls == [ME]


def test_pref_survives_week_change_and_cleared_with_character(client, monkeypatch):
    _pref(client, "본캐", "가토", "하드")
    _pref(client, "부캐", "가토", "노말")
    monkeypatch.setattr(db, "get_week_key", lambda *a, **k: "2099-W01")
    assert _prefs_of(_summary(client), "본캐")["가토"] == "하드"
    asyncio.run(db.remove_character(ME, "부캐"))
    assert asyncio.run(db.get_difficulty_prefs(ME)) == {("본캐", "가토"): "하드"}
