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


def test_ranking_by_combat_power_filters_by_role(seeded):
    """딜러/서포터 분리 — 홀리나이트(발키리)/바드는 서포터, 워로드는 딜러.
    role 필터는 combat_power에서만 적용된다."""
    support_rows = asyncio.run(db.get_expedition_ranking("combat_power", role="support"))
    assert [r["character_name"] for r in support_rows] == ["발키리", "바드"]

    dps_rows = asyncio.run(db.get_expedition_ranking("combat_power", role="dps"))
    assert [r["character_name"] for r in dps_rows] == ["워로드부캐"]


def test_ranking_role_filter_ignored_for_other_metrics(seeded):
    """role은 combat_power 전용 — item_level/weekly_clears에서는 무시되고 전체가 나온다."""
    il_rows = asyncio.run(db.get_expedition_ranking("item_level", role="support"))
    assert {r["character_name"] for r in il_rows} == {"발키리", "바드", "워로드부캐"}


def test_ranking_by_item_level_desc(seeded):
    rows = asyncio.run(db.get_expedition_ranking("item_level"))
    assert [r["character_name"] for r in rows] == ["발키리", "바드", "워로드부캐"]
    assert rows[0]["value"] == 1720.0


def test_ranking_by_weekly_clears(seeded):
    rows = asyncio.run(db.get_expedition_ranking("weekly_clears"))
    # 원정대(discord_id) 단위 합산 — 이 픽스처는 원정대당 클리어한 캐릭터가 하나뿐이라
    # 캐릭터 단위였을 때와 결과가 같아 보인다(대표 캐릭터 = 발키리/바드).
    assert [(r["character_name"], r["value"]) for r in rows] == [("발키리", 2), ("바드", 1)]
    assert rows[0]["character_class"] == "홀리나이트"  # user_characters와 조인돼 직업도 나온다
    assert rows[0]["discord_id"] == "111"


def test_ranking_weekly_clears_aggregates_multiple_characters_per_expedition(seeded):
    """개편: 같은 원정대(discord_id)의 여러 캐릭터가 각각 클리어해도 캐릭터별로 줄을
    나누지 않고 원정대 하나로 합산하며, 표시 이름/직업은 대표 캐릭터(최초 등록)를
    쓴다 — 캐릭터 단위로 흩어져 보이던 이전 방식 대신 "누가 가장 많이 클리어했는지"를
    한눈에 보여주기 위한 개편."""
    # 111의 두 번째 캐릭터(워로드부캐)도 이번 주 1건 클리어를 추가로 기록
    asyncio.run(db.toggle_completion("111", "워로드부캐", "카양겔", "하드"))

    rows = asyncio.run(db.get_expedition_ranking("weekly_clears"))
    by_discord = {r["discord_id"]: r for r in rows}

    assert len(rows) == 2  # 111, 222 각각 한 줄 — 워로드부캐가 별도 줄로 나오지 않는다
    assert by_discord["111"]["value"] == 3  # 발키리 2건 + 워로드부캐 1건 합산
    assert by_discord["111"]["character_name"] == "발키리"  # 대표(최초 등록) 캐릭터로 표시
    assert by_discord["222"]["value"] == 1


def test_ranking_excludes_characters_without_metric(seeded):
    """전투력이 없는 캐릭터는 전투력 랭킹에서 빠진다(0/None 제외)."""
    asyncio.run(db.add_character("222", "신규캐릭"))
    asyncio.run(db.update_character_cache("222", "신규캐릭", 1600.0, "기공사"))
    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert "신규캐릭" not in [r["character_name"] for r in rows]
    # 아이템레벨은 있으니 아이템레벨 랭킹엔 포함
    il_rows = asyncio.run(db.get_expedition_ranking("item_level"))
    assert "신규캐릭" in [r["character_name"] for r in il_rows]


def test_ranking_weekly_clears_excludes_unregistered_guest_characters(seeded):
    """회귀 테스트: 게스트 초대(API 키 미등록자)로 참여해 클리어된 캐릭터는
    user_characters에 매칭되는 행이 없어 이전에는 class/item_level이 NULL인 채로
    주간 클리어 랭킹에 노출됐다. 등록된 캐릭터만 나와야 한다."""
    week = db.get_week_key()
    asyncio.run(db.add_completion("999", "떠돌이게스트", "카멘", "하드", week))

    rows = asyncio.run(db.get_expedition_ranking("weekly_clears"))
    names = [r["character_name"] for r in rows]
    assert "떠돌이게스트" not in names
    assert names == ["발키리", "바드"]


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


def test_ranking_endpoint_applies_role_filter(seeded):
    from bot.api.server import app

    client = TestClient(app)
    resp = client.get(
        "/api/internal/ranking",
        params={"metric": "combat_power", "role": "support"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["role"] == "support"
    assert [e["character_name"] for e in body["entries"]] == ["발키리", "바드"]


def test_ranking_endpoint_ignores_invalid_role(seeded):
    from bot.api.server import app

    client = TestClient(app)
    resp = client.get(
        "/api/internal/ranking",
        params={"metric": "combat_power", "role": "healer"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["role"] is None
    assert len(body["entries"]) == 3


def test_update_combat_power_sets_value(seeded):
    asyncio.run(db.update_character_combat_power("111", "발키리", 4_500_000))
    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert rows[0]["value"] == 4_500_000
