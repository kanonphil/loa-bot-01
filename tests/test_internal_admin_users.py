"""bot/api/routes/internal.py의 관리자 전용 유저 관리 엔드포인트
(/api/internal/admin/users*) 검증 — Electron 관리자 앱에만 있던 기능을 웹에도
노출하기 위해 추가."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "111"
TARGET_ID = "222"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    import config
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})

    asyncio.run(db.set_user_api_key(TARGET_ID, "dummy-key"))
    asyncio.run(db.add_character(TARGET_ID, "메인캐릭"))
    asyncio.run(db.update_character_cache(TARGET_ID, "메인캐릭", 1710.0, "워로드"))
    asyncio.run(
        db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=TARGET_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("900", TARGET_ID, "메인캐릭", "워로드", "dps", 8))

    from bot.api.server import app

    return TestClient(app)


# ── 목록 ────────────────────────────────────────────────────

def test_list_users_returns_representative(client):
    resp = client.get("/api/internal/admin/users", params={"discord_id": ADMIN_ID}, headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    target = next(u for u in body if u["discord_id"] == TARGET_ID)
    assert target["representative"] == "메인캐릭"


def test_list_users_filters_by_query(client):
    resp = client.get(
        "/api/internal/admin/users", params={"discord_id": ADMIN_ID, "q": "메인"}, headers=HEADERS
    )
    body = resp.json()
    assert {u["discord_id"] for u in body} == {TARGET_ID}

    resp2 = client.get(
        "/api/internal/admin/users", params={"discord_id": ADMIN_ID, "q": "존재안함"}, headers=HEADERS
    )
    assert resp2.json() == []


def test_list_users_rejects_non_admin(client):
    resp = client.get("/api/internal/admin/users", params={"discord_id": TARGET_ID}, headers=HEADERS)
    assert resp.status_code == 403


def test_list_users_rejects_missing_webapp_key(client):
    resp = client.get("/api/internal/admin/users", params={"discord_id": ADMIN_ID})
    assert resp.status_code in (401, 403, 422)


# ── 캐릭터 ──────────────────────────────────────────────────

def test_user_characters_returns_cached_characters(client):
    resp = client.get(
        f"/api/internal/admin/users/{TARGET_ID}/characters",
        params={"discord_id": ADMIN_ID}, headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["character_name"] == "메인캐릭"
    assert body[0]["item_level"] == 1710.0


def test_user_characters_rejects_non_admin(client):
    resp = client.get(
        f"/api/internal/admin/users/{TARGET_ID}/characters",
        params={"discord_id": TARGET_ID}, headers=HEADERS,
    )
    assert resp.status_code == 403


# ── 참여 이력 ────────────────────────────────────────────────

def test_user_history_returns_entries(client):
    resp = client.get(
        f"/api/internal/admin/users/{TARGET_ID}/history",
        params={"discord_id": ADMIN_ID}, headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert body["entries"][0]["raid_name"] == "아르모체(4막)"


def test_user_history_rejects_non_admin(client):
    resp = client.get(
        f"/api/internal/admin/users/{TARGET_ID}/history",
        params={"discord_id": TARGET_ID}, headers=HEADERS,
    )
    assert resp.status_code == 403


# ── 삭제 ────────────────────────────────────────────────────

def test_delete_user_removes_data(client):
    resp = client.post(
        f"/api/internal/admin/users/{TARGET_ID}/delete",
        json={"discord_id": ADMIN_ID}, headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert asyncio.run(db.user_exists(TARGET_ID)) is False


def test_delete_user_rejects_non_admin(client):
    resp = client.post(
        f"/api/internal/admin/users/{TARGET_ID}/delete",
        json={"discord_id": TARGET_ID}, headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert asyncio.run(db.user_exists(TARGET_ID)) is True


# ── API 만료 의심(last_sync) ─────────────────────────────────

def test_list_users_includes_last_sync(client):
    resp = client.get("/api/internal/admin/users", params={"discord_id": ADMIN_ID}, headers=HEADERS)
    target = next(u for u in resp.json() if u["discord_id"] == TARGET_ID)
    assert target["last_sync"] is not None  # update_character_cache가 cached_at을 찍는다


def test_list_users_includes_character_count_and_last_active_at(client):
    import aiosqlite

    async def setup():
        await db.add_character(TARGET_ID, "부캐릭")
        await db.set_user_api_key("555", "dummy-key-5")  # 활동·캐릭터 전혀 없음
        await db.set_user_api_key("777", "dummy-key-7")
        async with aiosqlite.connect(db.DB_PATH) as conn:
            # 모든 활동 시각을 과거로 돌려 놓고 소스별로 최신값이 이기는지 본다
            await conn.execute("UPDATE party_slots SET joined_at='2026-01-01 00:00:00'")
            await conn.execute(
                "INSERT INTO party_comments (party_message_id, discord_id, author_name, content, source, created_at) "
                "VALUES ('900', ?, 'x', 'hi', 'web', '2026-02-01 00:00:00')", (TARGET_ID,)
            )
            await conn.execute(
                "INSERT INTO raid_completions (discord_id, character_name, raid_name, difficulty, week_key, completed_at) "
                "VALUES (?, '메인캐릭', '종막', '노말', '2026-03-04', '2026-03-05 12:00:00')", (TARGET_ID,)
            )
            await conn.commit()

    asyncio.run(setup())
    resp = client.get("/api/internal/admin/users", params={"discord_id": ADMIN_ID}, headers=HEADERS)
    rows = {u["discord_id"]: u for u in resp.json()}
    assert rows[TARGET_ID]["character_count"] == 2
    assert rows[TARGET_ID]["last_active_at"] == "2026-03-05 12:00:00"
    assert rows["555"]["character_count"] == 0
    assert rows["555"]["last_active_at"] is None

    # 웹 로그인/세션 재확인(verify-user)도 활동으로 센다
    assert client.get("/api/internal/verify-user", params={"discord_id": "777"}, headers=HEADERS).json()["registered"]
    rows = {u["discord_id"]: u for u in client.get(
        "/api/internal/admin/users", params={"discord_id": ADMIN_ID}, headers=HEADERS).json()}
    seen = rows["777"]["last_active_at"]
    assert seen is not None and "T" not in seen and seen > "2026-03-05 12:00:00"


def test_verify_user_does_not_create_row_for_unregistered(client):
    resp = client.get("/api/internal/verify-user", params={"discord_id": "888"}, headers=HEADERS)
    assert resp.json()["registered"] is False
    assert asyncio.run(db.user_exists("888")) is False


def test_get_stale_users_flags_never_synced_and_old(client):
    import aiosqlite

    async def setup():
        await db.set_user_api_key("555", "dummy-key-5")  # 캐릭터 없음 → 동기화 기록 없음
        await db.set_user_api_key("666", "dummy-key-6")
        await db.add_character("666", "오래된캐릭")
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE user_characters SET cached_at=datetime('now', '-40 days') WHERE discord_id='666'"
            )
            await conn.commit()

    asyncio.run(setup())
    stale = {u["discord_id"] for u in asyncio.run(db.get_stale_users(14))}
    assert "555" in stale and "666" in stale
    assert TARGET_ID not in stale  # 방금 동기화됨
