"""레이드 노출 순서 — raids_data.sort_order / is_pinned 검증.

기존에는 raids_data에 순서 컬럼이 없어서 카테고리 안 순서가 rowid(= 추가한 순서)로
고정됐고, 순서를 바꾸려면 삭제 후 재등록(= 난이도까지 날아감)밖에 방법이 없었다.
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
CAT = "카제로스"


def _fresh_db(tmp_path, monkeypatch, filename: str = "test.db") -> None:
    """init_db는 기본 레이드를 시드하므로, 순서를 검증하려면 비우고 시작한다."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / filename))
    asyncio.run(db.init_db())
    import sqlite3

    con = sqlite3.connect(db.DB_PATH)
    con.execute("DELETE FROM raid_difficulties")
    con.execute("DELETE FROM raids_data")
    con.execute("DELETE FROM raid_categories")
    con.commit()
    con.close()
    asyncio.run(db.add_category(CAT, 0))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from bot.api.server import app

    return TestClient(app)


def _add(name: str, category: str = CAT) -> None:
    asyncio.run(db.add_raid(name, name, "⚔️", category))
    asyncio.run(db.add_difficulty(name, "노말", 1600, 8, None, 1, 0))


def _order(category: str = CAT) -> list[str]:
    raids = asyncio.run(db.get_raids_dict())
    return [n for n, i in raids.items() if i["category"] == category]


# ── 자동 채번 ────────────────────────────────────────────

def test_add_raid_keeps_insertion_order(client):
    """추가한 순서가 그대로 유지된다 — sort_order를 전부 0으로 넣던 시절엔
    동점 처리돼서 rowid에 의존했다."""
    for n in ["1막", "2막", "3막"]:
        _add(n)
    assert _order() == ["1막", "2막", "3막"]
    assert asyncio.run(db.get_next_raid_sort_order(CAT)) == 3


def test_sort_order_is_scoped_per_category(client):
    asyncio.run(db.add_category("어비스", 1))
    _add("1막")
    _add("2막")
    _add("카양겔", category="어비스")
    assert asyncio.run(db.get_next_raid_sort_order("어비스")) == 1


# ── 배열 통째로 재정렬 ───────────────────────────────────

def test_reorder_raids_applies_whole_array(client):
    for n in ["1막", "2막", "3막", "4막"]:
        _add(n)
    count = asyncio.run(db.reorder_raids(CAT, ["4막", "1막", "3막", "2막"]))
    assert count == 4
    assert _order() == ["4막", "1막", "3막", "2막"]


def test_reorder_raids_keeps_unlisted_at_the_back(client):
    """배열에 빠진 레이드는 사라지지 않고 뒤로 밀리되 상대 순서를 유지한다 —
    관리 화면이 열려 있는 동안 다른 곳에서 레이드가 추가돼도 유실되지 않게."""
    for n in ["1막", "2막", "3막"]:
        _add(n)
    asyncio.run(db.reorder_raids(CAT, ["3막"]))
    assert _order() == ["3막", "1막", "2막"]


def test_reorder_raids_endpoint(client):
    for n in ["1막", "2막", "3막"]:
        _add(n)
    resp = client.put(
        "/api/raids/order",
        json={"category": CAT, "order": ["3막", "2막", "1막"]},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True, "count": 3}
    assert _order() == ["3막", "2막", "1막"]


def test_reorder_raids_requires_admin_key(client):
    _add("1막")
    resp = client.put("/api/raids/order", json={"category": CAT, "order": ["1막"]})
    assert resp.status_code == 401


def test_reorder_categories_endpoint(client):
    asyncio.run(db.add_category("어비스", 1))
    asyncio.run(db.add_category("그림자", 2))
    resp = client.put(
        "/api/raids/categories/order",
        json={"order": ["그림자", "어비스", CAT]},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    names = [c["name"] for c in asyncio.run(db.get_categories())]
    assert names == ["그림자", "어비스", CAT]


def test_reorder_difficulties_endpoint(client):
    _add("1막")
    asyncio.run(db.add_difficulty("1막", "하드", 1620, 8, None, 1, 1))
    resp = client.put(
        "/api/raids/1막/difficulties/order",
        json={"order": ["하드", "노말"]},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    raids = asyncio.run(db.get_raids_dict())
    assert list(raids["1막"]["difficulties"].keys()) == ["하드", "노말"]


# ── 카테고리 순서가 레이드 순서보다 우선 ─────────────────

def test_category_order_wins_over_raid_order(client):
    asyncio.run(db.add_category("어비스", 1))
    _add("1막")
    _add("카양겔", category="어비스")
    assert list(asyncio.run(db.get_raids_dict())) == ["1막", "카양겔"]

    asyncio.run(db.reorder_categories(["어비스", CAT]))
    assert list(asyncio.run(db.get_raids_dict())) == ["카양겔", "1막"]


# ── 상단 고정 ────────────────────────────────────────────

def test_pin_moves_raid_to_front_of_recruit_order(client):
    from bot.data import raids as raids_module

    asyncio.run(db.add_category("어비스", 1))
    _add("1막")
    _add("2막")
    _add("카양겔", category="어비스")

    resp = client.patch("/api/raids/카양겔/pin", json={"is_pinned": True}, headers=HEADERS)
    assert resp.json() == {"success": True}

    asyncio.run(raids_module.reload())
    assert [n for n, _ in raids_module.recruit_order()] == ["카양겔", "1막", "2막"]
    # RAIDS 자체(레이드 체크 등이 쓰는 카테고리 순서)는 그대로여야 한다
    assert list(raids_module.RAIDS) == ["1막", "2막", "카양겔"]


def test_recruit_order_excludes_inactive(client):
    from bot.data import raids as raids_module

    _add("1막")
    _add("2막")
    asyncio.run(db.set_raid_active("1막", False))
    asyncio.run(raids_module.reload())
    assert [n for n, _ in raids_module.recruit_order()] == ["2막"]


# ── 카테고리 이동 ────────────────────────────────────────

def test_move_raid_category_endpoint(client):
    asyncio.run(db.add_category("어비스", 1))
    _add("1막")
    _add("카양겔")
    resp = client.patch(
        "/api/raids/카양겔/category", json={"category": "어비스"}, headers=HEADERS
    )
    assert resp.json() == {"success": True}
    assert _order("어비스") == ["카양겔"]
    assert _order(CAT) == ["1막"]


def test_move_raid_to_unknown_category_fails(client):
    _add("1막")
    resp = client.patch(
        "/api/raids/1막/category", json={"category": "없는카테고리"}, headers=HEADERS
    )
    assert resp.json()["success"] is False


# ── 백필 마이그레이션 ────────────────────────────────────

def test_backfill_preserves_existing_rowid_order(tmp_path, monkeypatch):
    """sort_order 도입 전 DB(전부 0)를 열었을 때, 예전 정렬 기준이던 rowid 순서가
    그대로 보존돼야 한다 — 배포 직후 순서가 바뀌면 안 된다."""
    _fresh_db(tmp_path, monkeypatch, "legacy.db")
    for n in ["종막", "1막", "3막"]:
        asyncio.run(db.add_raid(n, n, "⚔️", CAT))

    # 컬럼이 없던 시절을 흉내 — 전부 0으로 되돌린다
    import sqlite3

    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE raids_data SET sort_order=0")
    con.commit()
    con.close()

    asyncio.run(db._migrate_backfill_raid_sort_order())
    assert _order() == ["종막", "1막", "3막"]


def test_backfill_does_not_touch_ordered_category(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch, "ordered.db")
    for n in ["1막", "2막", "3막"]:
        asyncio.run(db.add_raid(n, n, "⚔️", CAT))
    asyncio.run(db.reorder_raids(CAT, ["3막", "2막", "1막"]))

    asyncio.run(db._migrate_backfill_raid_sort_order())
    assert _order() == ["3막", "2막", "1막"]
