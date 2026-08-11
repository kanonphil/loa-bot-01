"""bot/api/routes/internal.py의 관리자(카테고리/레이드/난이도/직업 CRUD) 엔드포인트 검증.

웹앱은 X-Webapp-Key로만 인증하므로, 관리자 액션은 discord_id가 ADMIN_DISCORD_IDS에
있는지 매 요청마다 봇 서버가 다시 검증한다(_require_admin) — 이 재검증이 실제로
동작하는지가 이 테스트의 핵심."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
import config

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "111"
NON_ADMIN_ID = "222"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})
    asyncio.run(db.init_db())
    asyncio.run(db.add_category("카제로스", 0))
    asyncio.run(db.add_raid("카양겔", "종막", "⚔️", "카제로스"))
    asyncio.run(raids_module.reload())

    from bot.api.server import app

    return TestClient(app)


def test_non_admin_rejected_without_touching_db(client):
    before = asyncio.run(db.get_categories())
    resp = client.post(
        "/api/internal/admin/categories/add",
        json={"discord_id": NON_ADMIN_ID, "name": "새카테고리", "sort_order": 1},
        headers=HEADERS,
    )
    assert resp.json() == {"success": False, "reason": "관리자 권한이 없습니다."}
    assert asyncio.run(db.get_categories()) == before  # init_db()가 심어둔 기본 카테고리 외 추가 없음
    assert "새카테고리" not in {c["name"] for c in before}


def test_admin_category_crud(client):
    resp = client.post(
        "/api/internal/admin/categories/add",
        json={"discord_id": ADMIN_ID, "name": "익스트림", "sort_order": 1},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}

    resp = client.post(
        "/api/internal/admin/categories/extreme",
        json={"discord_id": ADMIN_ID, "name": "익스트림", "is_extreme": True},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    names = {c["name"]: c["is_extreme"] for c in asyncio.run(db.get_categories())}
    assert names["익스트림"] == 1

    resp = client.post(
        "/api/internal/admin/categories/delete",
        json={"discord_id": ADMIN_ID, "name": "익스트림"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert "익스트림" not in {c["name"] for c in asyncio.run(db.get_categories())}


def test_admin_raid_and_difficulty_crud_reloads_cache(client):
    resp = client.post(
        "/api/internal/admin/raids/add",
        json={
            "discord_id": ADMIN_ID, "name": "카멘", "short_name": "카멘",
            "icon": "🔥", "category": "카제로스",
        },
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert "카멘" in raids_module.RAIDS  # reload()가 실제로 in-place 캐시를 갱신했는지

    resp = client.post(
        "/api/internal/admin/difficulties/add",
        json={
            "discord_id": ADMIN_ID, "raid_name": "카멘", "difficulty": "노말",
            "min_level": 1600, "total_slots": 8, "party_split": None, "gates": 2,
        },
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert raids_module.RAIDS["카멘"]["difficulties"]["노말"]["min_level"] == 1600

    resp = client.post(
        "/api/internal/admin/raids/active",
        json={"discord_id": ADMIN_ID, "name": "카멘", "is_active": False},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert raids_module.RAIDS["카멘"]["is_active"] is False

    resp = client.post(
        "/api/internal/admin/difficulties/delete",
        json={"discord_id": ADMIN_ID, "raid_name": "카멘", "difficulty": "노말"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert raids_module.RAIDS["카멘"]["difficulties"] == {}

    resp = client.post(
        "/api/internal/admin/raids/delete",
        json={"discord_id": ADMIN_ID, "name": "카멘"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert "카멘" not in raids_module.RAIDS


def test_admin_job_class_crud(client):
    resp = client.post(
        "/api/internal/admin/classes/add",
        json={"discord_id": ADMIN_ID, "name": "커스텀서포터", "is_support": True},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    resp = client.get("/api/internal/job-classes", headers=HEADERS)
    assert {"name": "커스텀서포터", "is_support": 1} in resp.json()

    resp = client.post(
        "/api/internal/admin/classes/delete",
        json={"discord_id": ADMIN_ID, "name": "커스텀서포터"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    resp = client.get("/api/internal/job-classes", headers=HEADERS)
    assert "커스텀서포터" not in {c["name"] for c in resp.json()}


def test_webapp_key_still_required(client):
    resp = client.post(
        "/api/internal/admin/categories/add",
        json={"discord_id": ADMIN_ID, "name": "x", "sort_order": 0},
    )
    assert resp.status_code == 401
