"""회귀 테스트: _migrate_encrypt_api_keys가 부계정 테이블(user_api_keys)의 평문 키도
암호화해야 한다. 이전에는 users.loa_api_key만 처리해서, ENCRYPTION_KEY를 나중에 설정한
서버에서 그 이전에 등록된 부계정 키가 영구히 평문으로 DB에 남아 있었다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import aiosqlite
import pytest
from cryptography.fernet import Fernet

import bot.database.manager as db
import config


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))


async def _insert_plaintext_sub_account(discord_id: str, label: str, plain_key: str) -> int:
    """ENCRYPTION_KEY가 없던 시절에 등록된 것처럼, 암호화 없이 user_api_keys에 직접 삽입."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO user_api_keys (discord_id, label, api_key, added_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (discord_id, label, plain_key),
        )
        await conn.commit()
        return cur.lastrowid


def test_migration_encrypts_existing_plaintext_sub_account_keys(clean_db, monkeypatch):
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(config, "_fernet", fernet)

    async def scenario():
        await db.init_db()  # ENCRYPTION_KEY 없이 처음 부팅 — 아직 _fernet 반영 전 상태를 흉내
        key_id = await _insert_plaintext_sub_account("111", "부캐", "raw-plaintext-key")

        # 이제 ENCRYPTION_KEY가 설정된 것처럼(_fernet monkeypatch됨) 봇을 재시작 —
        # init_db가 다시 마이그레이션을 수행해야 한다.
        await db.init_db()

        async with aiosqlite.connect(db.DB_PATH) as conn:
            cur = await conn.execute("SELECT api_key FROM user_api_keys WHERE id=?", (key_id,))
            stored = (await cur.fetchone())[0]

        return stored, key_id

    stored, key_id = asyncio.run(scenario())

    assert stored != "raw-plaintext-key"  # 더 이상 평문이 아니어야 한다
    assert fernet.decrypt(stored.encode()).decode() == "raw-plaintext-key"
    # get_user_api_key_by_id는 여전히 원래 평문 키를 돌려줘야 한다(호출부 호환)
    decrypted = asyncio.run(db.get_user_api_key_by_id(key_id))
    assert decrypted == "raw-plaintext-key"


def test_migration_is_idempotent_and_leaves_already_encrypted_keys_alone(clean_db, monkeypatch):
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(config, "_fernet", fernet)

    async def scenario():
        await db.init_db()
        key_id = await db.add_user_api_key("111", "본계정", "already-plain-when-added")
        async with aiosqlite.connect(db.DB_PATH) as conn:
            cur = await conn.execute("SELECT api_key FROM user_api_keys WHERE id=?", (key_id,))
            before = (await cur.fetchone())[0]

        await db.init_db()  # 두 번째 init_db 실행 — 이미 암호화된 값은 안 건드려야 한다

        async with aiosqlite.connect(db.DB_PATH) as conn:
            cur = await conn.execute("SELECT api_key FROM user_api_keys WHERE id=?", (key_id,))
            after = (await cur.fetchone())[0]
        return before, after

    before, after = asyncio.run(scenario())
    assert before == after
