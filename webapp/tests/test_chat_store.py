"""webapp.chat_store가 실제로 동작하는지 검증 (세션/메시지 저장, 소유권, 보관기간 자동 삭제)."""
import os

os.environ.setdefault("DISCORD_CLIENT_ID", "test-client-id")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DISCORD_REDIRECT_URI", "http://localhost:8001/callback")
os.environ.setdefault("BOT_API_BASE_URL", "http://bot-server.internal")
os.environ.setdefault("BOT_API_WEBAPP_KEY", "test-webapp-key")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from webapp import chat_store, config


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "chat_test.db")
    monkeypatch.setattr(config, "CHAT_DB_PATH", path)
    asyncio.run(chat_store.init_db())
    return path


def test_create_session_and_add_messages(db_path):
    async def run():
        session_id = await chat_store.create_session("111", "블레이드 세팅 알려줘")
        await chat_store.add_message(session_id, "user", "블레이드 세팅 알려줘")
        await chat_store.add_message(session_id, "ai", "스텁 응답입니다")
        messages = await chat_store.get_messages(session_id)
        assert [m["role"] for m in messages] == ["user", "ai"]
        assert messages[0]["content"] == "블레이드 세팅 알려줘"

    asyncio.run(run())


def test_list_sessions_ordered_by_recent_activity(db_path):
    async def run():
        s1 = await chat_store.create_session("111", "첫 번째 질문")
        s2 = await chat_store.create_session("111", "두 번째 질문")
        # s1에 다시 메시지를 추가하면 updated_at이 갱신되어 목록 맨 위로 와야 함
        await chat_store.add_message(s1, "user", "추가 질문")

        sessions = await chat_store.list_sessions("111")
        assert [s["id"] for s in sessions] == [s1, s2]

    asyncio.run(run())


def test_list_sessions_scoped_to_discord_id(db_path):
    async def run():
        await chat_store.create_session("111", "유저1의 질문")
        await chat_store.create_session("222", "유저2의 질문")

        sessions_111 = await chat_store.list_sessions("111")
        assert len(sessions_111) == 1
        assert "유저1" in sessions_111[0]["title"]

    asyncio.run(run())


def test_session_ownership_check(db_path):
    async def run():
        session_id = await chat_store.create_session("111", "질문")
        assert await chat_store.session_belongs_to(session_id, "111") is True
        assert await chat_store.session_belongs_to(session_id, "222") is False
        assert await chat_store.session_belongs_to("no-such-id", "111") is False

    asyncio.run(run())


def test_delete_expired_sessions_removes_old_keeps_recent(db_path):
    async def run():
        old_session = await chat_store.create_session("111", "오래된 질문")
        recent_session = await chat_store.create_session("111", "최근 질문")

        # old_session의 updated_at을 40일 전으로 강제로 되돌림
        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
            await db.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (old_ts, old_session)
            )
            await db.commit()

        deleted_count = await chat_store.delete_expired_sessions(retention_days=30)
        assert deleted_count == 1

        remaining = await chat_store.list_sessions("111")
        assert [s["id"] for s in remaining] == [recent_session]

        # 삭제된 세션의 메시지도 같이 지워졌는지 확인
        async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM sessions WHERE id=?", (old_session,)
            )
            assert (await cur.fetchone())[0] == 0

    asyncio.run(run())
