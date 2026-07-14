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
    raid_name   TEXT,
    difficulty  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_reads (
    discord_id      TEXT NOT NULL,
    notification_id INTEGER NOT NULL,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (discord_id, notification_id)
);

CREATE TABLE IF NOT EXISTS notification_subscriptions (
    discord_id           TEXT PRIMARY KEY,
    subscribed           INTEGER NOT NULL DEFAULT 0,
    notify_created       INTEGER NOT NULL DEFAULT 1,
    notify_cleared       INTEGER NOT NULL DEFAULT 1,
    notify_guest_joined  INTEGER NOT NULL DEFAULT 1
);

-- 레이드+난이도 단위 알림 필터 (봇의 /레이드구독과 같은 개념).
-- 유저에게 필터가 하나도 없으면 "전체 레이드" 알림을 받는다.
-- difficulty가 NULL이면 그 레이드의 모든 난이도를 뜻한다.
CREATE TABLE IF NOT EXISTS notification_raid_filters (
    discord_id  TEXT NOT NULL,
    raid_name   TEXT NOT NULL,
    difficulty  TEXT,
    PRIMARY KEY (discord_id, raid_name, difficulty)
);

CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);
"""

# 기존 DB에 새 컬럼을 추가하는 마이그레이션 — 이미 있으면 sqlite가 에러를 내므로 무시한다.
_MIGRATIONS = [
    "ALTER TABLE notifications ADD COLUMN raid_name TEXT",
    "ALTER TABLE notifications ADD COLUMN difficulty TEXT",
    "ALTER TABLE notification_subscriptions ADD COLUMN notify_created INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE notification_subscriptions ADD COLUMN notify_cleared INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE notification_subscriptions ADD COLUMN notify_guest_joined INTEGER NOT NULL DEFAULT 1",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        await db.executescript(SCHEMA)
        for migration in _MIGRATIONS:
            try:
                await db.execute(migration)
            except aiosqlite.OperationalError:
                pass  # duplicate column — 이미 마이그레이션됨
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


EVENT_TYPES = ("created", "cleared", "guest_joined")
_TYPE_COLUMNS = {
    "created": "notify_created",
    "cleared": "notify_cleared",
    "guest_joined": "notify_guest_joined",
}


async def get_preferences(discord_id: str) -> dict:
    """구독 여부 + 종류별 on/off + 레이드 필터 목록.
    행이 없는 유저(설정 안 함)는 종류 전부 on, 필터 없음(=전체 레이드)이 기본값."""
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT subscribed, notify_created, notify_cleared, notify_guest_joined "
            "FROM notification_subscriptions WHERE discord_id=?",
            (discord_id,),
        )
        row = await cur.fetchone()
        cur = await db.execute(
            "SELECT raid_name, difficulty FROM notification_raid_filters "
            "WHERE discord_id=? ORDER BY raid_name, difficulty",
            (discord_id,),
        )
        filters = [dict(r) for r in await cur.fetchall()]
    return {
        "subscribed": bool(row and row["subscribed"]),
        "notify_created": bool(row["notify_created"]) if row else True,
        "notify_cleared": bool(row["notify_cleared"]) if row else True,
        "notify_guest_joined": bool(row["notify_guest_joined"]) if row else True,
        "raid_filters": filters,
    }


async def set_type_preferences(discord_id: str, created: bool, cleared: bool, guest_joined: bool) -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        await db.execute(
            "INSERT INTO notification_subscriptions "
            "(discord_id, subscribed, notify_created, notify_cleared, notify_guest_joined) "
            "VALUES (?, 0, ?, ?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET "
            "notify_created=excluded.notify_created, notify_cleared=excluded.notify_cleared, "
            "notify_guest_joined=excluded.notify_guest_joined",
            (discord_id, int(created), int(cleared), int(guest_joined)),
        )
        await db.commit()


async def add_raid_filter(discord_id: str, raid_name: str, difficulty: str | None) -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO notification_raid_filters (discord_id, raid_name, difficulty) "
            "VALUES (?, ?, ?)",
            (discord_id, raid_name, difficulty),
        )
        await db.commit()


async def remove_raid_filter(discord_id: str, raid_name: str, difficulty: str | None) -> None:
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        if difficulty is None:
            await db.execute(
                "DELETE FROM notification_raid_filters WHERE discord_id=? AND raid_name=? AND difficulty IS NULL",
                (discord_id, raid_name),
            )
        else:
            await db.execute(
                "DELETE FROM notification_raid_filters WHERE discord_id=? AND raid_name=? AND difficulty=?",
                (discord_id, raid_name, difficulty),
            )
        await db.commit()


def _matches(prefs: dict, event_type: str, raid_name: str | None, difficulty: str | None) -> bool:
    """이 알림이 유저의 종류 토글 + 레이드 필터를 통과하는지.
    레이드 정보가 없는 알림(구버전 데이터)은 필터로 거르지 않고 보여준다."""
    if not prefs.get(f"notify_{event_type}", True):
        return False
    filters = prefs.get("raid_filters") or []
    if not filters or raid_name is None:
        return True
    for f in filters:
        if f["raid_name"] == raid_name and (f["difficulty"] is None or f["difficulty"] == difficulty):
            return True
    return False


async def event_matches(discord_id: str, event_type: str, raid_name: str | None, difficulty: str | None) -> bool:
    """실시간 toast(SSE)에서 유저별로 이 이벤트를 보낼지 판단."""
    prefs = await get_preferences(discord_id)
    return _matches(prefs, event_type, raid_name, difficulty)


async def add_notification(
    event_type: str,
    message_id: str,
    text: str,
    raid_name: str | None = None,
    difficulty: str | None = None,
) -> dict:
    now = _now_iso()
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO notifications (type, message_id, text, raid_name, difficulty, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, message_id, text, raid_name, difficulty, now),
        )
        await db.commit()
        return {
            "id": cur.lastrowid,
            "type": event_type,
            "message_id": message_id,
            "text": text,
            "raid_name": raid_name,
            "difficulty": difficulty,
            "created_at": now,
        }


async def list_unread(discord_id: str, limit: int = 30) -> list[dict]:
    prefs = await get_preferences(discord_id)
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT n.id, n.type, n.message_id, n.text, n.raid_name, n.difficulty, n.created_at "
            "FROM notifications n "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM notification_reads r "
            "  WHERE r.notification_id = n.id AND r.discord_id = ?"
            ") "
            "ORDER BY n.id DESC",
            (discord_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    filtered = [r for r in rows if _matches(prefs, r["type"], r["raid_name"], r["difficulty"])]
    return filtered[:limit]


async def unread_count(discord_id: str) -> int:
    """읽지 않은 알림 수 — 종류 토글/레이드 필터 적용 후 개수라 list_unread를 재사용한다.
    (알림 보존 기간이 짧아 행 수가 적으므로 전체 조회 비용은 무시할 수준)"""
    return len(await list_unread(discord_id, limit=10**9))


async def list_read(discord_id: str, limit: int = 30) -> list[dict]:
    """이미 읽은 알림 — 종 아이콘 패널의 "읽음" 탭용. 종류 토글/레이드 필터는 동일하게 적용."""
    prefs = await get_preferences(discord_id)
    async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT n.id, n.type, n.message_id, n.text, n.raid_name, n.difficulty, n.created_at "
            "FROM notifications n "
            "JOIN notification_reads r ON r.notification_id = n.id AND r.discord_id = ? "
            "ORDER BY n.id DESC",
            (discord_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    filtered = [r for r in rows if _matches(prefs, r["type"], r["raid_name"], r["difficulty"])]
    return filtered[:limit]


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
