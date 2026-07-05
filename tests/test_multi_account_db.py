"""bot/database/manager.py의 다중 계정(부계정) API 키 관리 함수 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.database.manager as db


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def test_add_first_key_mirrors_legacy_column(clean_db):
    key_id = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))

    assert isinstance(key_id, int)
    assert asyncio.run(db.get_user_api_key("111")) == "key-a"
    keys = asyncio.run(db.list_user_api_keys("111"))
    assert len(keys) == 1
    assert keys[0]["label"] == "발키리"
    assert "api_key" not in keys[0]


def test_add_second_key_does_not_replace_first(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id2 = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))

    keys = asyncio.run(db.list_user_api_keys("111"))
    assert len(keys) == 2
    assert {k["id"] for k in keys} == {id1, id2}
    # 레거시 컬럼은 최초 등록된 키 그대로 유지
    assert asyncio.run(db.get_user_api_key("111")) == "key-a"


def test_get_user_api_key_by_id_decrypts(clean_db):
    key_id = asyncio.run(db.add_user_api_key("111", "발키리", "secret-key"))
    assert asyncio.run(db.get_user_api_key_by_id(key_id)) == "secret-key"


def test_remove_non_legacy_key_leaves_legacy_untouched(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id2 = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))

    removed = asyncio.run(db.remove_user_api_key("111", id2))
    assert removed is True
    assert asyncio.run(db.get_user_api_key("111")) == "key-a"
    keys = asyncio.run(db.list_user_api_keys("111"))
    assert len(keys) == 1
    assert keys[0]["id"] == id1


def test_remove_legacy_key_promotes_remaining(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id2 = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))

    removed = asyncio.run(db.remove_user_api_key("111", id1))
    assert removed is True
    # 레거시 키가 남은 유일한 계정(id2)로 승격
    assert asyncio.run(db.get_user_api_key("111")) == "key-b"
    keys = asyncio.run(db.list_user_api_keys("111"))
    assert len(keys) == 1
    assert keys[0]["id"] == id2


def test_remove_last_key_clears_legacy(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    removed = asyncio.run(db.remove_user_api_key("111", id1))
    assert removed is True
    assert asyncio.run(db.get_user_api_key("111")) is None
    assert asyncio.run(db.user_exists("111")) is False


def test_remove_key_not_belonging_to_user_fails(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    removed = asyncio.run(db.remove_user_api_key("222", id1))
    assert removed is False
    # 원래 유저 키는 그대로
    assert asyncio.run(db.get_user_api_key("111")) == "key-a"


def test_remove_key_leaves_character_api_key_id_null(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id1))

    asyncio.run(db.remove_user_api_key("111", id1))

    # 캐릭터 자체는 삭제되지 않고, api_key_id만 NULL이 된다
    chars = asyncio.run(db.get_user_characters("111"))
    assert chars == ["발키리"]
    remaining = asyncio.run(db.get_characters_by_api_key_id(id1))
    assert remaining == []


def test_get_all_api_keys_returns_all_users(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id2 = asyncio.run(db.add_user_api_key("222", "워로드", "key-b"))

    all_keys = asyncio.run(db.get_all_api_keys())
    ids = {k["id"] for k in all_keys}
    assert ids == {id1, id2}


def test_get_characters_by_api_key_id(clean_db):
    id1 = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id2 = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id1))
    asyncio.run(db.add_character("111", "슬레이어", api_key_id=id2))

    assert asyncio.run(db.get_characters_by_api_key_id(id1)) == ["발키리"]
    assert asyncio.run(db.get_characters_by_api_key_id(id2)) == ["슬레이어"]
