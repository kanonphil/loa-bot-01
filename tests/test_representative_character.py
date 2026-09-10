"""대표 캐릭터 선택 로직 검증 — user_api_keys.label(API 인증에 쓴 캐릭터)을
최우선으로 쓰고, 없으면 기존처럼 added_at 최솟값으로 폴백하는지.
get_invitable_users, get_expedition_ranking(weekly_clears), GET /api/users 세 곳이
같은 우선순위를 공유해야 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import aiosqlite
import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

DISCORD_ID = "111"


async def _set_added_at(discord_id: str, character_name: str, added_at: str) -> None:
    """added_at은 CURRENT_TIMESTAMP(초 단위)라 빠르게 연달아 add_character를 호출하면
    테스트에서도 같은 초에 찍혀 순서가 불확실해진다 — 순서를 명시적으로 고정한다."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "UPDATE user_characters SET added_at=? WHERE discord_id=? AND character_name=?",
            (added_at, discord_id, character_name),
        )
        await conn.commit()


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    return DISCORD_ID


def _add_characters_same_timestamp(discord_id: str, *names: str):
    """원정대 전체 자동 등록처럼 여러 캐릭터가 같은 타이밍에 들어오는 상황을 재현 —
    add_character만 쓰면 added_at이 CURRENT_TIMESTAMP로 전부 같아진다."""
    for name in names:
        asyncio.run(db.add_character(discord_id, name))


# ── get_invitable_users ────────────────────────────────────────

def test_representative_prefers_verified_character_over_insertion_order(seeded):
    """인증 캐릭터가 원정대 목록에서 나중에 등록돼도(added_at이 같은 상황) 대표로 뽑혀야 한다."""
    discord_id = seeded
    asyncio.run(db.set_user_api_key(discord_id, "dummy-key"))
    _add_characters_same_timestamp(discord_id, "MocaBlack", "MocaMoca", "MocaWhite")
    asyncio.run(db.add_user_api_key(discord_id, "MocaMoca", "dummy-key-2"))

    users = asyncio.run(db.get_invitable_users(set()))
    target = next(u for u in users if u["discord_id"] == discord_id)
    assert target["representative"] == "MocaMoca"


def test_representative_falls_back_to_added_at_without_api_key_label_match(seeded):
    discord_id = seeded
    asyncio.run(db.set_user_api_key(discord_id, "dummy-key"))
    asyncio.run(db.add_character(discord_id, "첫캐릭"))
    asyncio.run(db.add_character(discord_id, "둘째캐릭"))
    asyncio.run(_set_added_at(discord_id, "첫캐릭", "2026-01-01 00:00:00"))
    asyncio.run(_set_added_at(discord_id, "둘째캐릭", "2026-01-01 00:00:05"))

    users = asyncio.run(db.get_invitable_users(set()))
    target = next(u for u in users if u["discord_id"] == discord_id)
    assert target["representative"] == "첫캐릭"


# ── get_expedition_ranking(weekly_clears) ────────────────────────

def test_weekly_clears_ranking_uses_verified_character_as_representative(seeded):
    discord_id = seeded
    asyncio.run(db.set_user_api_key(discord_id, "dummy-key"))
    _add_characters_same_timestamp(discord_id, "알트캐릭", "메인캐릭")
    asyncio.run(db.add_user_api_key(discord_id, "메인캐릭", "dummy-key-2"))
    asyncio.run(db.update_character_cache(discord_id, "메인캐릭", 1700.0, "워로드"))

    asyncio.run(db.toggle_completion(discord_id, "알트캐릭", "아르모체(4막)", "노말"))

    ranking = asyncio.run(db.get_expedition_ranking("weekly_clears"))
    row = next(r for r in ranking if r["discord_id"] == discord_id)
    assert row["character_name"] == "메인캐릭"
    assert row["character_class"] == "워로드"


# ── GET /api/users ────────────────────────────────────────────

@pytest.fixture()
def client(seeded):
    from bot.api.server import app

    return TestClient(app)


def test_api_users_route_returns_verified_character_as_representative(client, seeded):
    discord_id = seeded
    asyncio.run(db.set_user_api_key(discord_id, "dummy-key"))
    _add_characters_same_timestamp(discord_id, "부캐릭터", "진짜본캐")
    asyncio.run(db.add_user_api_key(discord_id, "진짜본캐", "dummy-key-2"))

    resp = client.get("/api/users", headers={"X-API-Key": "test-admin-key"})

    assert resp.status_code == 200
    body = resp.json()
    target = next(u for u in body if u["discord_id"] == discord_id)
    assert target["representative"] == "진짜본캐"
