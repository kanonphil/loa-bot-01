"""/api/internal/raid-progress — 원정대 주간 진행률 집계.

웹앱 대시보드가 캐릭터마다 completions/raid-selection을 따로 부르던 걸 봇으로 옮긴
엔드포인트다. 옮기면서 규칙이 바뀌면 안 되므로, 웹에서 검증하던 규칙을 그대로 가져왔다:
  - 진행률은 난이도가 아니라 "레이드 단위"로 센다
  - 레이드 체크에서 고른 표시 레이드 선택을 존중한다
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
from bot.data import raids as raids_module

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ME = "111"
CHAR = "발키리"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    import sqlite3

    con = sqlite3.connect(db.DB_PATH)
    con.execute("DELETE FROM raid_difficulties")
    con.execute("DELETE FROM raids_data")
    con.execute("DELETE FROM raid_categories")
    con.commit()
    con.close()

    asyncio.run(db.add_category("카제로스", 0))
    asyncio.run(db.add_raid("아르모체(4막)", "4막", "🗡️", "카제로스"))
    asyncio.run(db.add_difficulty("아르모체(4막)", "노말", 1700, 8, 4, 2, 0))
    asyncio.run(db.add_raid("종막", "종막", "⚔️", "카제로스"))
    asyncio.run(db.add_difficulty("종막", "노말", 1690, 8, 4, 3, 0))
    asyncio.run(db.add_difficulty("종막", "하드", 1710, 8, 4, 3, 1))
    asyncio.run(raids_module.reload())

    asyncio.run(db.add_character(ME, CHAR))
    asyncio.run(db.update_character_cache(ME, CHAR, 1720.0, "홀리나이트"))

    from bot.api.server import app

    return TestClient(app)


def _progress(client) -> dict:
    resp = client.get("/api/internal/raid-progress", params={"discord_id": ME}, headers=HEADERS)
    assert resp.status_code == 200
    return resp.json()


def test_counts_raids_not_difficulties(client):
    """종막은 난이도가 둘이지만 레이드 1개로 센다 — 분모는 3이 아니라 2."""
    asyncio.run(db.toggle_completion(ME, CHAR, "종막", "하드"))
    body = _progress(client)
    assert body["total"] == 2
    assert body["done"] == 1


def test_all_done(client):
    asyncio.run(db.toggle_completion(ME, CHAR, "종막", "하드"))
    asyncio.run(db.toggle_completion(ME, CHAR, "아르모체(4막)", "노말"))
    body = _progress(client)
    assert (body["done"], body["total"]) == (2, 2)


def test_respects_raid_check_selection(client):
    """레이드 체크에서 표시 레이드를 골라뒀으면 진행률도 그 기준으로 센다
    (대시보드와 레이드 체크 카드가 항상 같은 숫자여야 한다)."""
    asyncio.run(db.set_selected_raids(ME, CHAR, ["아르모체(4막)"]))
    asyncio.run(db.toggle_completion(ME, CHAR, "종막", "하드"))
    body = _progress(client)
    assert body["total"] == 1
    assert body["done"] == 0


def test_excludes_raids_above_item_level(client):
    asyncio.run(db.add_raid("미래레이드", "미래", "🔮", "카제로스"))
    asyncio.run(db.add_difficulty("미래레이드", "노말", 9999, 8, 4, 1, 0))
    asyncio.run(raids_module.reload())
    assert _progress(client)["total"] == 2


def test_per_character_remaining(client):
    asyncio.run(db.toggle_completion(ME, CHAR, "종막", "노말"))
    entry = _progress(client)["characters"][0]
    assert entry["character_name"] == CHAR
    assert entry["remaining"] == 1
    assert entry["item_level"] == 1720.0


def test_stale_cache_still_counts(client):
    """캐시가 오래된 캐릭터도 진행률에서 빠지면 안 된다 —
    get_cached_characters 기본값(6시간)을 그대로 쓰면 레벨이 None이 되어 0/0이 된다."""
    import sqlite3

    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE user_characters SET cached_at = datetime('now', '-30 days')")
    con.commit()
    con.close()
    assert _progress(client)["total"] == 2


def test_no_characters(client):
    resp = client.get(
        "/api/internal/raid-progress", params={"discord_id": "없는유저"}, headers=HEADERS
    )
    assert resp.json() == {
        "week_key": db.get_week_key(), "characters": [], "done": 0, "total": 0
    }


def test_requires_webapp_key(client):
    resp = client.get("/api/internal/raid-progress", params={"discord_id": ME})
    assert resp.status_code == 401
