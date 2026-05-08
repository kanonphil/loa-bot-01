import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = "loa_bot.db"
KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id   TEXT PRIMARY KEY,
    loa_api_key  TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_characters (
    discord_id      TEXT,
    character_name  TEXT,
    item_level      REAL,
    character_class TEXT,
    cached_at       TIMESTAMP,
    added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, character_name)
);

CREATE TABLE IF NOT EXISTS raid_completions (
    discord_id     TEXT,
    character_name TEXT,
    raid_name      TEXT,
    difficulty     TEXT,
    week_key       TEXT,
    completed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, character_name, raid_name, difficulty, week_key)
);

CREATE TABLE IF NOT EXISTS parties (
    message_id          TEXT PRIMARY KEY,
    channel_id          TEXT,
    guild_id            TEXT,
    leader_id           TEXT,
    raid_name           TEXT,
    difficulty          TEXT,
    proficiency         TEXT,
    scheduled_time      TEXT,
    scheduled_datetime  TEXT,
    total_slots         INTEGER,
    min_level           INTEGER,
    status              TEXT DEFAULT 'recruiting',
    notified            INTEGER DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS party_slots (
    party_message_id TEXT,
    slot_number      INTEGER,
    discord_id       TEXT,
    character_name   TEXT,
    character_class  TEXT,
    role             TEXT DEFAULT 'dps',
    joined_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (party_message_id, slot_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_party_user
    ON party_slots(party_message_id, discord_id);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id         TEXT PRIMARY KEY,
    forum_channel_id TEXT
);
"""


def get_week_key() -> str:
    """수요일 06:00 KST 기준 현재 주 키 반환"""
    now = datetime.now(KST)
    days_since_wed = (now.weekday() - 2) % 7
    week_start = (now - timedelta(days=days_since_wed)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if week_start > now:
        week_start -= timedelta(days=7)
    return week_start.strftime("%Y-%m-%d")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # 기존 DB 마이그레이션 (컬럼 없으면 추가)
        for col, definition in [
            ("scheduled_datetime", "TEXT"),
            ("notified",           "INTEGER DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE parties ADD COLUMN {col} {definition}")
            except Exception:
                pass
        try:
            await db.execute("ALTER TABLE party_slots ADD COLUMN role TEXT DEFAULT 'dps'")
        except Exception:
            pass
        for col, definition in [
            ("item_level",      "REAL"),
            ("character_class", "TEXT"),
            ("cached_at",       "TIMESTAMP"),
        ]:
            try:
                await db.execute(f"ALTER TABLE user_characters ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await db.commit()


# ──────────────────────────────────────────────
# 서버 설정
# ──────────────────────────────────────────────

async def set_forum_channel(guild_id: str, forum_channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guild_settings (guild_id, forum_channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET forum_channel_id=excluded.forum_channel_id",
            (guild_id, forum_channel_id),
        )
        await db.commit()


async def get_forum_channel_id(guild_id: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT forum_channel_id FROM guild_settings WHERE guild_id=?", (guild_id,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


# ──────────────────────────────────────────────
# 사용자 API 키
# ──────────────────────────────────────────────

async def set_user_api_key(discord_id: str, api_key: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (discord_id, loa_api_key) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET loa_api_key=excluded.loa_api_key",
            (discord_id, api_key),
        )
        await db.commit()


async def get_user_api_key(discord_id: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT loa_api_key FROM users WHERE discord_id=?", (discord_id,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


# ──────────────────────────────────────────────
# 캐릭터 등록
# ──────────────────────────────────────────────

async def add_character(discord_id: str, character_name: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO user_characters (discord_id, character_name) VALUES (?, ?)",
                (discord_id, character_name),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_character(discord_id: str, character_name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM user_characters WHERE discord_id=? AND character_name=?",
            (discord_id, character_name),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_user_characters(discord_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT character_name FROM user_characters WHERE discord_id=? ORDER BY added_at",
            (discord_id,),
        )
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def update_character_cache(
    discord_id: str, character_name: str, item_level: float, character_class: str
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_characters SET item_level=?, character_class=?, cached_at=CURRENT_TIMESTAMP "
            "WHERE discord_id=? AND character_name=?",
            (item_level, character_class, discord_id, character_name),
        )
        await db.commit()


async def get_cached_characters(discord_id: str, max_age_hours: int = 6) -> list[dict]:
    """캐시된 캐릭터 목록. max_age_hours 이상 지난 항목은 item_level=None 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT character_name, character_class, "
            "CASE WHEN cached_at >= datetime('now', ?) THEN item_level ELSE NULL END AS item_level "
            "FROM user_characters WHERE discord_id=? ORDER BY added_at",
            (f"-{max_age_hours} hours", discord_id),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# 레이드 체크
# ──────────────────────────────────────────────

async def get_completions(discord_id: str, character_name: str) -> set[str]:
    week = get_week_key()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT raid_name, difficulty FROM raid_completions "
            "WHERE discord_id=? AND character_name=? AND week_key=?",
            (discord_id, character_name, week),
        )
        rows = await cur.fetchall()
    return {f"{r[0]}_{r[1]}" for r in rows}


async def toggle_completion(
    discord_id: str, character_name: str, raid_name: str, difficulty: str
) -> bool:
    week = get_week_key()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM raid_completions "
            "WHERE discord_id=? AND character_name=? AND raid_name=? AND difficulty=? AND week_key=?",
            (discord_id, character_name, raid_name, difficulty, week),
        )
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM raid_completions "
                "WHERE discord_id=? AND character_name=? AND raid_name=? AND difficulty=? AND week_key=?",
                (discord_id, character_name, raid_name, difficulty, week),
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO raid_completions (discord_id, character_name, raid_name, difficulty, week_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (discord_id, character_name, raid_name, difficulty, week),
            )
            await db.commit()
            return True


# ──────────────────────────────────────────────
# 파티
# ──────────────────────────────────────────────

async def create_party(
    message_id: str,
    channel_id: str,
    guild_id: str,
    leader_id: str,
    raid_name: str,
    difficulty: str,
    proficiency: str,
    scheduled_time: str,
    scheduled_datetime: str | None,
    total_slots: int,
    min_level: int,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO parties (message_id, channel_id, guild_id, leader_id, "
            "raid_name, difficulty, proficiency, scheduled_time, scheduled_datetime, "
            "total_slots, min_level) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id, channel_id, guild_id, leader_id,
                raid_name, difficulty, proficiency, scheduled_time, scheduled_datetime,
                total_slots, min_level,
            ),
        )
        await db.commit()


async def get_parties_due_notification(now_iso: str) -> list[dict]:
    """알림 시간이 된 미통보 파티 목록"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM parties "
            "WHERE scheduled_datetime IS NOT NULL "
            "AND scheduled_datetime <= ? "
            "AND notified = 0 "
            "AND status IN ('recruiting', 'full', 'closed')",
            (now_iso,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_notified(message_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET notified=1 WHERE message_id=?", (message_id,)
        )
        await db.commit()


async def get_party(message_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM parties WHERE message_id=?", (message_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_party_by_channel(channel_id: str) -> Optional[dict]:
    """Forum Thread ID(channel_id)로 파티 조회."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM parties WHERE channel_id=?", (channel_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_party_slots(message_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM party_slots WHERE party_message_id=? ORDER BY slot_number",
            (message_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]



async def auto_assign_slot(
    message_id: str,
    discord_id: str,
    character_name: str,
    character_class: str,
    role: str,
    total_slots: int,
    *,
    party_group: int | None = None,
    party_split: int | None = None,
) -> tuple[bool, int, str]:
    """자동 슬롯 배정.
    party_group/party_split 지정 시 해당 파티 슬롯 범위 내에서만 배정.
    반환: (success, slot_number, message)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT slot_number FROM party_slots WHERE party_message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        existing = await cur.fetchone()
        if existing:
            return False, 0, f"이미 **{existing[0]}번** 슬롯에 참여 중입니다."

        cur = await db.execute(
            "SELECT slot_number FROM party_slots WHERE party_message_id=? ORDER BY slot_number",
            (message_id,),
        )
        taken = {r[0] for r in await cur.fetchall()}

        if party_group and party_split:
            start = (party_group - 1) * party_split + 1
            end   = start + party_split
            available = [s for s in range(start, end) if s not in taken]
            if not available:
                return False, 0, f"{party_group}파티에 빈 자리가 없습니다."
            # 서포터 중복 체크 (파티당 1명 제한)
            if role == "support":
                cur = await db.execute(
                    "SELECT COUNT(*) FROM party_slots "
                    "WHERE party_message_id=? AND slot_number >= ? AND slot_number < ? AND role='support'",
                    (message_id, start, end),
                )
                support_count = (await cur.fetchone())[0]
                if support_count >= 1:
                    return False, 0, f"{party_group}파티에 이미 서포터가 있습니다."
        else:
            available = [s for s in range(1, total_slots + 1) if s not in taken]
            if not available:
                return False, 0, "빈 슬롯이 없습니다."
            # 단일 파티 서포터 중복 체크
            if role == "support":
                cur = await db.execute(
                    "SELECT COUNT(*) FROM party_slots "
                    "WHERE party_message_id=? AND role='support'",
                    (message_id,),
                )
                support_count = (await cur.fetchone())[0]
                if support_count >= 1:
                    return False, 0, "이미 파티에 서포터가 있습니다."

        slot_number = available[0]

        await db.execute(
            "INSERT INTO party_slots "
            "(party_message_id, slot_number, discord_id, character_name, character_class, role) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, slot_number, discord_id, character_name, character_class, role),
        )

        cur = await db.execute(
            "SELECT COUNT(*), p.total_slots FROM party_slots ps "
            "JOIN parties p ON p.message_id = ps.party_message_id "
            "WHERE ps.party_message_id=?",
            (message_id,),
        )
        count, total = await cur.fetchone()
        if count >= total:
            await db.execute(
                "UPDATE parties SET status='full' WHERE message_id=? AND status='recruiting'",
                (message_id,)
            )

        await db.commit()
    return True, slot_number, "참여 완료"


async def leave_slot(message_id: str, discord_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM party_slots WHERE party_message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        if cur.rowcount > 0:
            await db.execute(
                "UPDATE parties SET status='recruiting' WHERE message_id=? AND status='full'",
                (message_id,),
            )
            await db.commit()
            return True
        await db.commit()
        return False


async def transfer_leader(message_id: str, new_leader_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET leader_id=? WHERE message_id=?",
            (new_leader_id, message_id),
        )
        await db.commit()


async def complete_raid_for_party(message_id: str) -> int:
    """파티원 전체 레이드 완료 처리 (INSERT OR IGNORE — 중복 토글 없음).
    반환: 처리된 인원 수
    """
    party = await get_party(message_id)
    if not party:
        return 0
    slots    = await get_party_slots(message_id)
    week     = get_week_key()
    raid_name  = party["raid_name"]
    difficulty = party["difficulty"]
    count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for slot in slots:
            cur = await db.execute(
                "INSERT OR IGNORE INTO raid_completions "
                "(discord_id, character_name, raid_name, difficulty, week_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (slot["discord_id"], slot["character_name"], raid_name, difficulty, week),
            )
            if cur.rowcount > 0:
                count += 1
        await db.commit()
    return count


async def disband_party(message_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET status='disbanded' WHERE message_id=?", (message_id,)
        )
        await db.commit()


async def close_party(message_id: str) -> None:
    """모집만 마감 (파티는 유지 — 클리어 가능)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET status='closed' WHERE message_id=?", (message_id,)
        )
        await db.commit()


async def get_user_parties(discord_id: str) -> list[dict]:
    """특정 유저가 참여 중인 활성 파티 목록."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT DISTINCT p.* FROM parties p "
            "JOIN party_slots ps ON p.message_id = ps.party_message_id "
            "WHERE ps.discord_id=? AND p.status IN ('recruiting', 'full', 'closed') "
            "ORDER BY p.created_at DESC",
            (discord_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_guild_parties(guild_id: str) -> list[dict]:
    """서버의 모집 중/완성된 파티 목록 (최신순)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM parties WHERE guild_id=? AND status IN ('recruiting', 'full', 'closed') "
            "ORDER BY created_at DESC",
            (guild_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_expired_parties(cutoff_iso: str) -> list[dict]:
    """scheduled_datetime이 cutoff_iso 이전인 미종료 파티."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM parties "
            "WHERE scheduled_datetime IS NOT NULL "
            "AND scheduled_datetime <= ? "
            "AND status IN ('recruiting', 'full')",
            (cutoff_iso,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_active_party_ids() -> list[tuple[str, str]]:
    """봇 재시작 시 활성 파티 복구용. (message_id, channel_id) 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id, channel_id FROM parties WHERE status IN ('recruiting', 'full', 'closed')"
        )
        rows = await cur.fetchall()
    return [(r[0], r[1]) for r in rows]
