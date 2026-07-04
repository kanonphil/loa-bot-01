"""AI 채팅 세션/메시지 저장소.
봇 서버의 SQLite(길드 데이터)와는 완전히 분리된, webapp 자체 소유 DB.
봇 서버는 이 데이터의 존재를 몰라도 되고, 봇 서버에 쓰기 부하를 더하지 않는다.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite

from webapp import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    discord_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_discord_id ON sessions(discord_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


def _make_title(first_message: str) -> str:
    first_message = first_message.strip()
    return first_message[:30] + ("…" if len(first_message) > 30 else "")


async def create_session(discord_id: str, first_message: str) -> str:
    session_id = uuid.uuid4().hex
    now = _now_iso()
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        await db.execute(
            "INSERT INTO sessions (id, discord_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, discord_id, _make_title(first_message), now, now),
        )
        await db.commit()
    return session_id


async def add_message(session_id: str, role: str, content: str) -> None:
    now = _now_iso()
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        await db.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
        )
        await db.commit()


async def list_sessions(discord_id: str, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, title, updated_at FROM sessions "
            "WHERE discord_id=? ORDER BY updated_at DESC LIMIT ?",
            (discord_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def session_belongs_to(session_id: str, discord_id: str) -> bool:
    """다른 사람 세션 id를 추측해서 들어오는 걸 막기 위한 소유권 확인."""
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM sessions WHERE id=? AND discord_id=?", (session_id, discord_id)
        )
        return await cur.fetchone() is not None


async def get_messages(session_id: str) -> list[dict]:
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def delete_expired_sessions(retention_days: int) -> int:
    """updated_at 기준 retention_days보다 오래된 세션+메시지 삭제. 삭제된 세션 수 반환."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    async with aiosqlite.connect(config.CHAT_DB_PATH) as db:
        cur = await db.execute("SELECT id FROM sessions WHERE updated_at < ?", (cutoff,))
        expired_ids = [row[0] for row in await cur.fetchall()]
        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            await db.execute(
                f"DELETE FROM messages WHERE session_id IN ({placeholders})", expired_ids
            )
            await db.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})", expired_ids
            )
            await db.commit()
    return len(expired_ids)
