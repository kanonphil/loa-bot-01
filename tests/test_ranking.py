"""전체 원정대 랭킹 — DB 집계 함수 + 봇 내부 /ranking 엔드포인트 검증.
캐시된 값만 읽으므로 Lost Ark API 호출은 없다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))

    async def setup():
        await db.init_db()
        # 두 유저의 여러 캐릭터 — 전체 원정대 대상
        await db.add_character("111", "발키리")
        await db.add_character("111", "워로드부캐")
        await db.add_character("222", "바드")
        await db.update_character_cache("111", "발키리", 1720.0, "홀리나이트")
        await db.update_character_cache("111", "워로드부캐", 1700.0, "워로드")
        await db.update_character_cache("222", "바드", 1710.0, "바드")
        await db.update_character_combat_power("111", "발키리", 4_300_000)
        await db.update_character_combat_power("111", "워로드부캐", 3_900_000)
        await db.update_character_combat_power("222", "바드", 4_100_000)
        # 주간 클리어 — 발키리 2건, 바드 1건 (워로드부캐 0건)
        week = db.get_week_key()
        for raid, diff in [("카멘", "하드"), ("종막", "하드")]:
            await db.toggle_completion("111", "발키리", raid, diff)
        await db.toggle_completion("222", "바드", "카멘", "하드")

    asyncio.run(setup())
    return tmp_path


def test_ranking_by_combat_power_desc(seeded):
    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert [r["character_name"] for r in rows] == ["발키리", "바드", "워로드부캐"]
    assert rows[0]["value"] == 4_300_000
    # 전체 원정대(서로 다른 유저)가 함께 순위에 든다
    assert {r["discord_id"] for r in rows} == {"111", "222"}


def test_ranking_by_item_level_desc(seeded):
    rows = asyncio.run(db.get_expedition_ranking("item_level"))
    assert [r["character_name"] for r in rows] == ["발키리", "바드", "워로드부캐"]
    assert rows[0]["value"] == 1720.0


def test_ranking_by_weekly_clears(seeded):
    rows = asyncio.run(db.get_expedition_ranking("weekly_clears"))
    # 클리어 기록이 있는 캐릭터만, 많은 순
    assert [(r["character_name"], r["value"]) for r in rows] == [("발키리", 2), ("바드", 1)]
    assert rows[0]["character_class"] == "홀리나이트"  # user_characters와 조인돼 직업도 나온다


def test_ranking_excludes_characters_without_metric(seeded):
    """전투력이 없는 캐릭터는 전투력 랭킹에서 빠진다(0/None 제외)."""
    asyncio.run(db.add_character("222", "신규캐릭"))
    asyncio.run(db.update_character_cache("222", "신규캐릭", 1600.0, "기공사"))
    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert "신규캐릭" not in [r["character_name"] for r in rows]
    # 아이템레벨은 있으니 아이템레벨 랭킹엔 포함
    il_rows = asyncio.run(db.get_expedition_ranking("item_level"))
    assert "신규캐릭" in [r["character_name"] for r in il_rows]


def test_ranking_endpoint(seeded):
    from bot.api.server import app

    client = TestClient(app)
    resp = client.get("/api/internal/ranking", params={"metric": "combat_power"}, headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "combat_power"
    assert body["entries"][0]["character_name"] == "발키리"


def test_ranking_endpoint_defaults_invalid_metric(seeded):
    from bot.api.server import app

    client = TestClient(app)
    resp = client.get("/api/internal/ranking", params={"metric": "hax"}, headers=HEADERS)
    assert resp.json()["metric"] == "combat_power"


def test_update_combat_power_sets_value(seeded):
    asyncio.run(db.update_character_combat_power("111", "발키리", 4_500_000))
    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert rows[0]["value"] == 4_500_000
