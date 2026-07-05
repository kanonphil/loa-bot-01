"""부계정 기능 배포 이전에 등록한 유저의 user_api_keys 백필 마이그레이션 검증.

버그: /원정대·/캐릭터등록 등은 db.list_user_api_keys(discord_id)로 등록 여부를
판단하는데, 이 테이블은 부계정 기능과 함께 새로 생겨서 그 이전에 /api등록을
마친 유저는(키가 users.loa_api_key에만 있음) 여기에 아무 행도 없다. 그 결과
이미 등록된 유저가 "먼저 /api등록 해주세요" 안내를 다시 받는 문제가 있었다.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import asyncio

import pytest

import bot.database.manager as db

DISCORD_ID = "111"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_legacy_user_gets_backfilled_into_user_api_keys(db_path):
    async def run():
        # 부계정 기능 이전 가입자 재현: users.loa_api_key만 있고 user_api_keys는 비어있음,
        # 캐릭터도 api_key_id 없이(NULL) 등록돼 있음.
        await db.init_db()
        await db.set_user_api_key(DISCORD_ID, "legacy-plaintext-key")
        await db.add_character(DISCORD_ID, "레거시캐릭")

        assert await db.list_user_api_keys(DISCORD_ID) == []  # 마이그레이션 전에는 비어있어야 함

        await db._migrate_backfill_user_api_keys()

        accounts = await db.list_user_api_keys(DISCORD_ID)
        assert len(accounts) == 1
        assert accounts[0]["label"] == "레거시캐릭"  # 기존 캐릭터명을 라벨로 사용

        # 기존 캐릭터도 이 계정 소속으로 연결돼야 한다
        characters = await db.get_cached_characters_with_account(DISCORD_ID, max_age_hours=99999)
        assert characters[0]["account_label"] == "레거시캐릭"

    asyncio.run(run())


def test_legacy_user_without_any_character_gets_default_label(db_path):
    async def run():
        await db.init_db()
        await db.set_user_api_key(DISCORD_ID, "legacy-plaintext-key")

        await db._migrate_backfill_user_api_keys()

        accounts = await db.list_user_api_keys(DISCORD_ID)
        assert len(accounts) == 1
        assert accounts[0]["label"] == "기본 계정"

    asyncio.run(run())


def test_already_migrated_or_new_user_is_not_touched_twice(db_path):
    """부계정 기능 배포 후 새로 등록한 유저는 이미 user_api_keys가 있으므로
    백필 대상이 아니다 — 중복 행이 생기면 안 된다."""
    async def run():
        await db.init_db()
        await db.add_user_api_key(DISCORD_ID, "발키리", "some-key")

        await db._migrate_backfill_user_api_keys()

        accounts = await db.list_user_api_keys(DISCORD_ID)
        assert len(accounts) == 1
        assert accounts[0]["label"] == "발키리"

    asyncio.run(run())


def test_migration_is_idempotent_across_multiple_init_db_calls(db_path):
    """봇 재시작할 때마다 init_db가 호출되므로, 여러 번 실행돼도 중복 생성되면 안 된다."""
    async def run():
        await db.init_db()
        await db.set_user_api_key(DISCORD_ID, "legacy-plaintext-key")
        await db.add_character(DISCORD_ID, "레거시캐릭")

        await db.init_db()
        await db.init_db()

        accounts = await db.list_user_api_keys(DISCORD_ID)
        assert len(accounts) == 1

    asyncio.run(run())
