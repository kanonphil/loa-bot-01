"""bot/database/manager.py의 캐릭터별 레이드 선택(get/set_selected_raids) 검증.

레이드가 늘어나도(4개→7개+) 카드가 안 길어지게, 캐릭터마다 어떤 레이드를 보여줄지
직접 고를 수 있어야 한다. 핵심은 "한 번도 고른 적 없음"(전체 표시, None)과
"골랐는데 전부 해제함"(빈 리스트, 아무것도 표시 안 함)을 구분하는 것."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import asyncio

import pytest

import bot.database.manager as db

DISCORD_ID = "111"
CHAR = "발키리"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    asyncio.run(db.init_db())
    return path


def test_never_customized_returns_none(db_path):
    result = asyncio.run(db.get_selected_raids(DISCORD_ID, CHAR))
    assert result is None


def test_set_then_get_returns_selection(db_path):
    asyncio.run(db.set_selected_raids(DISCORD_ID, CHAR, ["카멘", "종막"]))
    result = asyncio.run(db.get_selected_raids(DISCORD_ID, CHAR))
    assert set(result) == {"카멘", "종막"}


def test_deselecting_everything_returns_empty_list_not_none(db_path):
    """전부 해제한 상태는 "한 번도 안 골랐음"과 달라야 한다 — None이면 안 되고 빈 리스트여야 함."""
    asyncio.run(db.set_selected_raids(DISCORD_ID, CHAR, ["카멘"]))
    asyncio.run(db.set_selected_raids(DISCORD_ID, CHAR, []))
    result = asyncio.run(db.get_selected_raids(DISCORD_ID, CHAR))
    assert result == []


def test_resaving_selection_replaces_previous(db_path):
    asyncio.run(db.set_selected_raids(DISCORD_ID, CHAR, ["카멘", "종막"]))
    asyncio.run(db.set_selected_raids(DISCORD_ID, CHAR, ["세르카"]))
    result = asyncio.run(db.get_selected_raids(DISCORD_ID, CHAR))
    assert result == ["세르카"]


def test_selection_is_scoped_per_character(db_path):
    asyncio.run(db.set_selected_raids(DISCORD_ID, "발키리", ["카멘"]))
    result = asyncio.run(db.get_selected_raids(DISCORD_ID, "워로드부캐"))
    assert result is None  # 다른 캐릭터는 영향 없음


def test_selection_is_scoped_per_discord_id(db_path):
    asyncio.run(db.set_selected_raids("111", CHAR, ["카멘"]))
    result = asyncio.run(db.get_selected_raids("222", CHAR))
    assert result is None
