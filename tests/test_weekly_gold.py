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


def _mine_only(client, name, raids=("가토", "나비")):
    client.post("/api/internal/raid-selection", json={"discord_id": ME, "character_name": name, "raid_names": list(raids)}, headers=WEB)


def test_migration_adds_nullable_clear_gold_and_is_idempotent(client):
    asyncio.run(db.init_db())  # 두 번 돌려도 문제없다
    con = sqlite3.connect(db.DB_PATH)
    cols = {r[1]: r for r in con.execute("PRAGMA table_info(raid_difficulties)")}
    con.close()
    assert "clear_gold" in cols and cols["clear_gold"][3] == 0  # NOT NULL 아님


def test_raids_exposes_clear_gold_and_difficulty_gold(client):
    raids = client.get("/api/internal/raids", headers=WEB).json()
    assert raids["가토"]["difficulties"]["하드"]["clear_gold"] == 2000
    assert raids["가토"]["difficulty_gold"] == {"노말": 1000, "하드": 2000, "나메": 9000}
    assert raids["나비"]["difficulty_gold"] == {"노말": 500, "하드": None}
    assert list(raids["가토"]["difficulties"]) == ["노말", "하드", "나메"]  # 기존 필드 그대로


def test_summary_gold_sums(client):
    _mine_only(client, "본캐")
    _mine_only(client, "부캐")
    s = _summary(client)
    main = next(c for c in s["characters"] if c["character_name"] == "본캐")
    alt = next(c for c in s["characters"] if c["character_name"] == "부캐")
    gato = next(r for r in main["applicable_raids"] if r["raid_name"] == "가토")
    assert gato["difficulties"] == ["노말", "하드"]  # 이름 목록은 그대로
    assert gato["difficulty_gold"] == {"노말": 1000, "하드": 2000}
    # 아직 아무것도 안 함: 본캐 = 가토 최대 2000 + 나비 최대 500(하드는 미입력=0) / 부캐 = 1000 + 500
    assert (main["gold_earned"], main["gold_total"]) == (0, 2500)
    assert (alt["gold_earned"], alt["gold_total"]) == (0, 1500)
    assert s["gold"] == {"earned": 0, "total": 4000}

    # 본캐가 가토 노말을 끝냄 → 그 레이드는 끝낸 난이도 골드(1000)로 확정
    client.post("/api/internal/completions/toggle",
                json={"discord_id": ME, "character_name": "본캐", "raid_name": "가토", "difficulty": "노말"}, headers=WEB)
    # 나비 하드(골드 미입력)를 끝냄 → 0으로 확정
    client.post("/api/internal/completions/toggle",
                json={"discord_id": ME, "character_name": "본캐", "raid_name": "나비", "difficulty": "하드"}, headers=WEB)
    main = next(c for c in _summary(client)["characters"] if c["character_name"] == "본캐")
    assert (main["gold_earned"], main["gold_total"]) == (1000, 1000)
    assert _summary(client)["gold"] == {"earned": 1000, "total": 2500}


def test_summary_gold_respects_visible_selection(client):
    _mine_only(client, "본캐", raids=("가토",))
    _mine_only(client, "부캐", raids=())
    s = _summary(client)
    main = next(c for c in s["characters"] if c["character_name"] == "본캐")
    assert main["gold_total"] == 2000
    assert s["gold"] == {"earned": 0, "total": 2000}


def test_admin_difficulty_clear_gold_add_update_keep_and_clear(client):
    def post(path, **body):
        return client.post(f"/api/internal/admin/difficulties/{path}", json={"discord_id": ADMIN_ID, **body}, headers=WEB).json()

    base = {"raid_name": "나비", "min_level": 1600, "total_slots": 4, "gates": 1}
    assert post("add", difficulty="헬", clear_gold=-1, **base)["success"] is False
    assert post("add", difficulty="헬", clear_gold=700, **base) == {"success": True}
    assert raids_module.RAIDS["나비"]["difficulty_gold"]["헬"] == 700

    # clear_gold를 안 보내면 기존 값 유지(골드 칸이 없는 예전 폼 호환)
    assert post("update", difficulty="헬", **{**base, "min_level": 1610}) == {"success": True}
    assert raids_module.RAIDS["나비"]["difficulties"]["헬"]["clear_gold"] == 700
    assert raids_module.RAIDS["나비"]["difficulties"]["헬"]["min_level"] == 1610

    assert post("update", difficulty="헬", clear_gold=800, **base) == {"success": True}
    assert raids_module.RAIDS["나비"]["difficulty_gold"]["헬"] == 800
    assert post("update", difficulty="헬", clear_gold=None, **base) == {"success": True}
    assert raids_module.RAIDS["나비"]["difficulty_gold"]["헬"] is None
    assert post("update", difficulty="헬", clear_gold=-5, **base)["success"] is False
