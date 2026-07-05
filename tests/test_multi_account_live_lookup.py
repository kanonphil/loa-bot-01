"""bot/cogs/dashboard.py, bot/cogs/raid.py — 부계정 캐릭터를 조회할 때 해당 계정의
API 키로 로스트아크 API를 호출하는지 검증. (레거시 단일 키만 쓰면 부계정 캐릭터를
조회할 때 엉뚱한 키로 호출하게 되는 버그가 있었다 — 이를 막는 회귀 테스트.)"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.database.manager as db
from bot.cogs.dashboard import _resolve_api_key_for_character as dashboard_resolve
from bot.cogs.raid import _resolve_api_key_for_character as raid_resolve


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def test_dashboard_resolve_uses_sub_account_key_when_character_belongs_to_it(clean_db):
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id_a))
    asyncio.run(db.add_character("111", "슬레이어", api_key_id=id_b))

    # 레거시 컬럼(fallback)은 key-a인데, "슬레이어"는 key-b 소속이어야 함
    resolved = asyncio.run(dashboard_resolve("111", "슬레이어", "key-a"))
    assert resolved == "key-b"


def test_dashboard_resolve_falls_back_to_legacy_key_for_untracked_character(clean_db):
    asyncio.run(db.add_character("111", "레거시캐릭"))  # api_key_id 없음
    resolved = asyncio.run(dashboard_resolve("111", "레거시캐릭", "legacy-key"))
    assert resolved == "legacy-key"


def test_raid_resolve_uses_sub_account_key_when_character_belongs_to_it(clean_db):
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("111", "슬레이어부캐", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id_a))
    asyncio.run(db.add_character("111", "슬레이어", api_key_id=id_b))

    resolved = asyncio.run(raid_resolve("111", "슬레이어", "key-a"))
    assert resolved == "key-b"


def test_raid_resolve_falls_back_to_legacy_key_for_untracked_character(clean_db):
    asyncio.run(db.add_character("111", "레거시캐릭"))
    resolved = asyncio.run(raid_resolve("111", "레거시캐릭", "legacy-key"))
    assert resolved == "legacy-key"
