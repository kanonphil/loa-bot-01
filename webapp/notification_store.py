"""공대 알림(생성/클리어/게스트 합류) 이력 저장소.
봇 서버의 SQLite(길드 데이터)와는 완전히 분리된, webapp 자체 소유 DB.
알림 자체는 전역(길드 전체) 이벤트 1건이고, 유저별 읽음 여부만 별도 테이블로 추적한다
— 구독 안 한 유저는 애초에 조회하지 않으므로 별도 필터링이 필요 없다.
"""
from datetime import datetime, timedelta, timezone

import aiosqlite

from webapp import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_reads (
    discord_id      TEXT NOT NULL,
    notification_id INTEGER NOT NULL,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (discord_id, notification_id)
);

CREATE TABLE IF NOT EXISTS notification_subscriptions (
    discord_id  TEXT PRIMARY KEY,
    subscribed  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def is_subscribed(discord_id: str) -> bool:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        cur = await db.execute(
            "SELECT subscribed FROM notification_subscriptions WHERE discord_id=?", (discord_id,)
        )
        row = await cur.fetchone()
        return bool(row and row[0])


async def set_subscribed(discord_id: str, subscribed: bool) -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        await db.execute(
            "INSERT INTO notification_subscriptions (discord_id, subscribed) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET subscribed=excluded.subscribed",
            (discord_id, int(subscribed)),
        )
        await db.commit()


async def add_notification(event_type: str, message_id: str, text: str) -> dict:
    now = _now_iso()
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO notifications (type, message_id, text, created_at) VALUES (?, ?, ?, ?)",
            (event_type, message_id, text, now),
        )
        await db.commit()
        return {
            "id": cur.lastrowid,
            "type": event_type,
            "message_id": message_id,
            "text": text,
            "created_at": now,
        }


async def list_unread(discord_id: str, limit: int = 30) -> list[dict]:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT n.id, n.type, n.message_id, n.text, n.created_at FROM notifications n "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM notification_reads r "
            "  WHERE r.notification_id = n.id AND r.discord_id = ?"
            ") "
            "ORDER BY n.id DESC LIMIT ?",
            (discord_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def unread_count(discord_id: str) -> int:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM notifications n "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM notification_reads r "
            "  WHERE r.notification_id = n.id AND r.discord_id = ?"
            ")",
            (discord_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def mark_read(discord_id: str, notification_id: int) -> dict | None:
    """읽음 처리하고 해당 알림을 반환(상세 페이지로 리다이렉트할 message_id를 얻기 위함)."""
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, type, message_id, text, created_at FROM notifications WHERE id=?",
            (notification_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "INSERT OR IGNORE INTO notification_reads (discord_id, notification_id, read_at) "
            "VALUES (?, ?, ?)",
            (discord_id, notification_id, _now_iso()),
        )
        await db.commit()
        return dict(row)


async def delete_expired(retention_days: int) -> int:
    """created_at 기준 retention_days보다 오래된 알림+읽음기록 삭제. 삭제된 알림 수 반환."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        cur = await db.execute("SELECT id FROM notifications WHERE created_at < ?", (cutoff,))
        expired_ids = [row[0] for row in await cur.fetchall()]
        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            await db.execute(
                f"DELETE FROM notification_reads WHERE notification_id IN ({placeholders})", expired_ids
            )
            await db.execute(
                f"DELETE FROM notifications WHERE id IN ({placeholders})", expired_ids
            )
            await db.commit()
    return len(expired_ids)
