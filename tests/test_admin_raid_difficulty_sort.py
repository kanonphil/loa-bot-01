"""bot/api/routes/raids.py — 난이도 표시 순서 버그 수정 검증.

버그: 난이도 추가 시 sort_order를 항상 0으로 넣어서 모든 난이도가 동점 처리되고,
결과적으로 (raid_name, difficulty) 복합 PK 인덱스 스캔 순서 — 즉 가나다 순 —로
보이던 문제. "노말" → "하드" → "나이트메어" 순으로 추가해도 관리자 앱 드롭다운에는
"나이트메어"가 맨 위로 뜨는 현상.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-API-Key": "test-admin-key"}
RAID_NAME = "카양겔"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.add_category("카제로스", 0))
    asyncio.run(db.add_raid(RAID_NAME, "종막", "⚔️", "카제로스"))

    from bot.api.server import app

    return TestClient(app)


def test_difficulties_keep_insertion_order_not_alphabetical(client):
    """노말 → 하드 → 나이트메어 순으로 추가하면, 가나다 순(나이트메어가 먼저)이 아니라
    추가한 순서 그대로 응답에 담겨야 한다."""
    for diff, level in [("노말", 1600), ("하드", 1620), ("나이트메어", 1640)]:
        resp = client.post(
            f"/api/raids/{RAID_NAME}/difficulties",
            json={"difficulty": diff, "min_level": level, "total_slots": 8, "gates": 1},
            headers=HEADERS,
        )
        assert resp.json() == {"success": True}

    resp = client.get(f"/api/raids/{RAID_NAME}/difficulties", headers=HEADERS)
    assert list(resp.json().keys()) == ["노말", "하드", "나이트메어"]


def test_sort_difficulty_updates_order(client):
    for diff, level in [("노말", 1600), ("하드", 1620), ("나이트메어", 1640)]:
        client.post(
            f"/api/raids/{RAID_NAME}/difficulties",
            json={"difficulty": diff, "min_level": level, "total_slots": 8, "gates": 1},
            headers=HEADERS,
        )

    # "나이트메어"를 맨 앞으로 끌어올림 (sort_order 0)
    resp = client.patch(
        f"/api/raids/{RAID_NAME}/difficulties/나이트메어/sort",
        json={"sort_order": 0},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}

    resp = client.get(f"/api/raids/{RAID_NAME}/difficulties", headers=HEADERS)
    assert list(resp.json().keys())[0] == "나이트메어"


def test_sort_difficulty_requires_admin_key(client):
    resp = client.patch(
        f"/api/raids/{RAID_NAME}/difficulties/노말/sort",
        json={"sort_order": 0},
    )
    assert resp.status_code == 401


def test_get_next_difficulty_sort_order_starts_at_zero(client):
    assert asyncio.run(db.get_next_difficulty_sort_order(RAID_NAME)) == 0
    asyncio.run(db.add_difficulty(RAID_NAME, "노말", 1600, 8, None, 1, 0))
    assert asyncio.run(db.get_next_difficulty_sort_order(RAID_NAME)) == 1
    asyncio.run(db.add_difficulty(RAID_NAME, "하드", 1620, 8, None, 1, 1))
    assert asyncio.run(db.get_next_difficulty_sort_order(RAID_NAME)) == 2


def test_get_next_difficulty_sort_order_is_scoped_per_raid(client):
    asyncio.run(db.add_raid("카멘", "카멘", "🔥", "카제로스"))
    asyncio.run(db.add_difficulty(RAID_NAME, "노말", 1600, 8, None, 1, 0))
    asyncio.run(db.add_difficulty(RAID_NAME, "하드", 1620, 8, None, 1, 1))

    assert asyncio.run(db.get_next_difficulty_sort_order("카멘")) == 0
