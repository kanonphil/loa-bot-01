"""bot/api/routes/internal.py 검증: 웹앱 키 인증 + 등록 여부 조회가 실제로 동작하는지."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import tempfile

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 실제 loa_bot.db를 건드리지 않도록 임시 DB로 교체
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.set_user_api_key("111", "dummy-loa-key"))

    from bot.api.server import app

    return TestClient(app)


def test_wrong_webapp_key_rejected(client):
    resp = client.get(
        "/api/internal/verify-user",
        params={"discord_id": "111"},
        headers={"X-Webapp-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_missing_webapp_key_rejected(client):
    resp = client.get("/api/internal/verify-user", params={"discord_id": "111"})
    assert resp.status_code in (401, 403)  # APIKeyHeader raises 403 when header absent


def test_registered_user_returns_true(client):
    resp = client.get(
        "/api/internal/verify-user",
        params={"discord_id": "111"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"discord_id": "111", "registered": True}


def test_unregistered_user_returns_false(client):
    resp = client.get(
        "/api/internal/verify-user",
        params={"discord_id": "999999"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"discord_id": "999999", "registered": False}


def test_admin_key_does_not_work_on_internal_route(client):
    """관리자 키로는 내부 API가 열리면 안 된다 (권한 분리 확인)."""
    resp = client.get(
        "/api/internal/verify-user",
        params={"discord_id": "111"},
        headers={"X-Webapp-Key": "test-admin-key"},
    )
    assert resp.status_code == 401


def test_user_characters_returns_cached_characters(client):
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1680.0, character_class="서포터")
    )

    resp = client.get(
        "/api/internal/user-characters",
        params={"discord_id": "111"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["character_name"] == "발키리"
    assert data[0]["character_class"] == "서포터"
    assert data[0]["item_level"] == 1680.0


def test_user_characters_empty_for_user_with_none(client):
    resp = client.get(
        "/api/internal/user-characters",
        params={"discord_id": "222"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ── 레이드 체크 ────────────────────────────────────────────
# db.init_db()가 비어있는 DB에는 항상 기본 레이드 데이터(seed_game_data)를
# 자동으로 채워넣으므로, 그 기본 데이터를 그대로 사용해서 테스트한다.

def test_raids_endpoint_returns_seeded_default_raids(client):
    resp = client.get(
        "/api/internal/raids", headers={"X-Webapp-Key": "test-webapp-key"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "아르모체(4막)" in data
    assert data["아르모체(4막)"]["difficulties"]["노말"]["min_level"] == 1700
    assert data["아르모체(4막)"]["difficulties"]["하드"]["min_level"] == 1720


def test_raid_categories_endpoint(client):
    resp = client.get(
        "/api/internal/raid-categories", headers={"X-Webapp-Key": "test-webapp-key"}
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["카제로스", "그림자", "어비스"]  # sort_order 순


def test_completions_endpoint_empty_by_default(client):
    resp = client.get(
        "/api/internal/completions",
        params={"discord_id": "111", "character_name": "발키리"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["completions"] == []
    assert body["week_key"]  # 현재 주 키가 채워져 있어야 함


def test_toggle_completion_marks_then_unmarks(client):
    toggle_url = "/api/internal/completions/toggle"
    payload = {
        "discord_id": "111",
        "character_name": "발키리",
        "raid_name": "아르모체(4막)",
        "difficulty": "노말",
    }

    first = client.post(toggle_url, json=payload, headers={"X-Webapp-Key": "test-webapp-key"})
    assert first.status_code == 200
    assert first.json() == {"completed": True}

    check = client.get(
        "/api/internal/completions",
        params={"discord_id": "111", "character_name": "발키리"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert check.json()["completions"] == ["아르모체(4막)_노말"]

    second = client.post(toggle_url, json=payload, headers={"X-Webapp-Key": "test-webapp-key"})
    assert second.json() == {"completed": False}

    check_again = client.get(
        "/api/internal/completions",
        params={"discord_id": "111", "character_name": "발키리"},
        headers={"X-Webapp-Key": "test-webapp-key"},
    )
    assert check_again.json()["completions"] == []
