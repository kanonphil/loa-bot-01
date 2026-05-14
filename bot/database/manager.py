import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import encrypt_api_key, decrypt_api_key, is_plaintext_key

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
    memo                TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS party_waitlist (
    party_message_id TEXT,
    discord_id       TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (party_message_id, discord_id)
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

CREATE TABLE IF NOT EXISTS raid_categories (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_extreme INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raids_data (
    name            TEXT PRIMARY KEY,
    short_name      TEXT NOT NULL,
    icon            TEXT NOT NULL DEFAULT '⚔️',
    category        TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    available_from  TEXT,
    available_until TEXT
);

CREATE TABLE IF NOT EXISTS raid_difficulties (
    raid_name   TEXT NOT NULL,
    difficulty  TEXT NOT NULL,
    min_level   INTEGER NOT NULL,
    total_slots INTEGER NOT NULL,
    party_split INTEGER,
    gates       INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (raid_name, difficulty)
);

CREATE TABLE IF NOT EXISTS job_classes (
    name       TEXT PRIMARY KEY,
    is_support INTEGER NOT NULL DEFAULT 0
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


def get_week_key_for_dt(dt_iso: str) -> str:
    """임의 ISO datetime 문자열에 해당하는 주 키 반환."""
    dt = datetime.fromisoformat(dt_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    days_since_wed = (dt.weekday() - 2) % 7
    week_start = (dt - timedelta(days=days_since_wed)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if week_start > dt:
        week_start -= timedelta(days=7)
    return week_start.strftime("%Y-%m-%d")


def get_week_start_iso() -> str:
    """현재 주 시작 시각(수요일 06:00 KST)을 ISO 문자열로 반환."""
    now = datetime.now(KST)
    days_since_wed = (now.weekday() - 2) % 7
    week_start = (now - timedelta(days=days_since_wed)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if week_start > now:
        week_start -= timedelta(days=7)
    return week_start.isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # 기존 DB 마이그레이션 (컬럼 없으면 추가)
        for col, definition in [
            ("scheduled_datetime", "TEXT"),
            ("notified",           "INTEGER DEFAULT 0"),
            ("memo",               "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE parties ADD COLUMN {col} {definition}")
            except Exception:
                pass
        for col, definition in [
            ("is_extreme", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE raid_categories ADD COLUMN {col} {definition}")
            except Exception:
                pass
        for col, definition in [
            ("is_active",       "INTEGER NOT NULL DEFAULT 1"),
            ("available_from",  "TEXT"),
            ("available_until", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE raids_data ADD COLUMN {col} {definition}")
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
    await seed_game_data()
    await _migrate_encrypt_api_keys()


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

async def _migrate_encrypt_api_keys() -> None:
    """ENCRYPTION_KEY 설정 시 기존 평문 API 키를 암호화 (1회성 마이그레이션)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT discord_id, loa_api_key FROM users")
        rows = await cur.fetchall()
        migrated = 0
        for discord_id, stored in rows:
            if stored and is_plaintext_key(stored):
                await db.execute(
                    "UPDATE users SET loa_api_key=? WHERE discord_id=?",
                    (encrypt_api_key(stored), discord_id),
                )
                migrated += 1
        if migrated > 0:
            await db.commit()
            print(f"[DB] API 키 암호화 마이그레이션 완료: {migrated}개")


async def delete_user(discord_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE discord_id=?", (discord_id,))
        await db.commit()


async def set_user_api_key(discord_id: str, api_key: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (discord_id, loa_api_key) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET loa_api_key=excluded.loa_api_key",
            (discord_id, encrypt_api_key(api_key)),
        )
        await db.commit()


async def get_user_api_key(discord_id: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT loa_api_key FROM users WHERE discord_id=?", (discord_id,)
        )
        row = await cur.fetchone()
    return decrypt_api_key(row[0]) if row else None


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

async def get_completions(
    discord_id: str, character_name: str, week_key: str | None = None
) -> set[str]:
    week = week_key if week_key is not None else get_week_key()
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
    memo: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO parties (message_id, channel_id, guild_id, leader_id, "
            "raid_name, difficulty, proficiency, scheduled_time, scheduled_datetime, "
            "total_slots, min_level, memo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id, channel_id, guild_id, leader_id,
                raid_name, difficulty, proficiency, scheduled_time, scheduled_datetime,
                total_slots, min_level, memo,
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


async def get_user_active_slots_in_raid(
    discord_id: str, raid_name: str, exclude_message_id: str,
    party_week_key: str | None = None,
) -> list[dict]:
    """같은 레이드의 다른 활성 파티에 이미 참여 중인 슬롯 목록.
    party_week_key가 주어지면 같은 주차 파티만 반환한다.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT ps.character_name, p.scheduled_datetime FROM party_slots ps "
            "JOIN parties p ON ps.party_message_id = p.message_id "
            "WHERE ps.discord_id = ? "
            "AND p.raid_name = ? "
            "AND p.message_id != ? "
            "AND p.status IN ('recruiting', 'full', 'closed')",
            (discord_id, raid_name, exclude_message_id),
        )
        rows = await cur.fetchall()

    if party_week_key is None:
        return [dict(r) for r in rows]

    result = []
    current_week = get_week_key()
    for r in rows:
        row = dict(r)
        sdt = row.get("scheduled_datetime")
        other_week = get_week_key_for_dt(sdt) if sdt else current_week
        if other_week == party_week_key:
            result.append(row)
    return result


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
    slots = await get_party_slots(message_id)
    # 파티 일정 주차 기준으로 기록 (당주 클리어가 아닌 경우에도 올바른 주차 반영)
    if party.get("scheduled_datetime"):
        week = get_week_key_for_dt(party["scheduled_datetime"])
    else:
        week = get_week_key()
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
        await db.execute(
            "DELETE FROM party_waitlist WHERE party_message_id=?", (message_id,)
        )
        await db.commit()


# ──────────────────────────────────────────────
# 빈자리 알림 대기열
# ──────────────────────────────────────────────

async def add_waitlist(message_id: str, discord_id: str) -> bool:
    """대기열 등록. 이미 있으면 False 반환."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO party_waitlist (party_message_id, discord_id) VALUES (?, ?)",
                (message_id, discord_id),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_waitlist(message_id: str, discord_id: str) -> bool:
    """대기열 취소. 없으면 False 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM party_waitlist WHERE party_message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_waitlist(message_id: str) -> list[str]:
    """대기열 discord_id 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT discord_id FROM party_waitlist WHERE party_message_id=? ORDER BY created_at",
            (message_id,),
        )
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def clear_waitlist(message_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM party_waitlist WHERE party_message_id=?", (message_id,)
        )
        await db.commit()


async def update_party_memo(message_id: str, memo: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET memo=? WHERE message_id=?", (memo, message_id)
        )
        await db.commit()


async def update_party_schedule(
    message_id: str, scheduled_time: str, scheduled_datetime: str
) -> None:
    """일정 변경. notified=0 리셋으로 새 시간에 알림이 재발송된다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET scheduled_time=?, scheduled_datetime=?, notified=0 "
            "WHERE message_id=?",
            (scheduled_time, scheduled_datetime, message_id),
        )
        await db.commit()


async def close_party(message_id: str) -> None:
    """모집만 마감 (파티는 유지 — 클리어 가능)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET status='closed' WHERE message_id=?", (message_id,)
        )
        await db.commit()


async def reopen_party(message_id: str) -> None:
    """모집 재개 — 파티원이 가득 찼으면 full, 아니면 recruiting으로 복원."""
    party = await get_party(message_id)
    if not party or party["status"] != "closed":
        return
    slots = await get_party_slots(message_id)
    new_status = "full" if len(slots) >= party["total_slots"] else "recruiting"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET status=? WHERE message_id=?", (new_status, message_id)
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


async def get_prev_week_disbanded_parties(week_start_iso: str) -> list[dict]:
    """현재 주 시작 이전에 scheduled된 disbanded 파티 (스레드 삭제용).
    scheduled_datetime이 없는 파티는 created_at 기준으로 현재 주 이전 파티를 포함한다.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM parties "
            "WHERE status = 'disbanded' "
            "AND (scheduled_datetime < ? OR (scheduled_datetime IS NULL AND created_at < ?))",
            (week_start_iso, week_start_iso),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def purge_party(message_id: str) -> None:
    """파티·슬롯·대기열 레코드를 완전히 삭제한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM party_slots    WHERE party_message_id=?", (message_id,))
        await db.execute("DELETE FROM party_waitlist WHERE party_message_id=?", (message_id,))
        await db.execute("DELETE FROM parties         WHERE message_id=?",       (message_id,))
        await db.commit()


async def get_prev_week_active_parties(week_start_iso: str) -> list[dict]:
    """현재 주 시작 이전인 미종료 파티 (주간 리셋 정리용).
    scheduled_datetime이 없는 파티는 created_at 기준으로 판단한다.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM parties "
            "WHERE status IN ('recruiting', 'full', 'closed') "
            "AND (scheduled_datetime < ? OR (scheduled_datetime IS NULL AND created_at < ?))",
            (week_start_iso, week_start_iso),
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


# ──────────────────────────────────────────────
# 게임 데이터 (레이드 / 직업) — DB 기반 관리
# ──────────────────────────────────────────────

# ── 카테고리 ───────────────────────────────────

async def get_categories() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT name, sort_order, is_extreme FROM raid_categories ORDER BY sort_order"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_category(name: str, sort_order: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO raid_categories (name, sort_order) VALUES (?, ?)",
                (name, sort_order),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_category(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM raid_categories WHERE name=?", (name,)
        )
        await db.commit()
        return cur.rowcount > 0


async def update_category_sort(name: str, sort_order: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE raid_categories SET sort_order=? WHERE name=?", (sort_order, name)
        )
        await db.commit()
        return cur.rowcount > 0


# ── 레이드 ─────────────────────────────────────

async def get_raids_dict() -> dict:
    """RAIDS 딕셔너리 포맷으로 반환 (카테고리 순 → 난이도 순)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT r.name, r.short_name, r.icon, r.category, "
            "r.is_active, r.available_from, r.available_until, c.is_extreme, "
            "d.difficulty, d.min_level, d.total_slots, d.party_split, d.gates "
            "FROM raids_data r "
            "JOIN raid_categories c ON r.category = c.name "
            "LEFT JOIN raid_difficulties d ON r.name = d.raid_name "
            "ORDER BY c.sort_order, r.rowid, d.sort_order"
        )
        rows = await cur.fetchall()
    result: dict = {}
    for row in rows:
        r = dict(row)
        name = r["name"]
        if name not in result:
            result[name] = {
                "short_name":     r["short_name"],
                "icon":           r["icon"],
                "category":       r["category"],
                "is_extreme":     bool(r["is_extreme"]),
                "is_active":      bool(r["is_active"]),
                "available_from": r["available_from"],
                "available_until":r["available_until"],
                "difficulties":   {},
            }
        if r["difficulty"]:
            result[name]["difficulties"][r["difficulty"]] = {
                "min_level":  r["min_level"],
                "total_slots":r["total_slots"],
                "party_split":r["party_split"],
                "gates":      r["gates"],
            }
    return result


async def add_raid(name: str, short_name: str, icon: str, category: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO raids_data (name, short_name, icon, category) VALUES (?, ?, ?, ?)",
                (name, short_name, icon, category),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_raid(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM raid_difficulties WHERE raid_name=?", (name,)
        )
        cur = await db.execute("DELETE FROM raids_data WHERE name=?", (name,))
        await db.commit()
        return cur.rowcount > 0


async def raid_exists(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM raids_data WHERE name=?", (name,)
        )
        return await cur.fetchone() is not None


async def update_category_extreme(name: str, is_extreme: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE raid_categories SET is_extreme=? WHERE name=?",
            (int(is_extreme), name),
        )
        await db.commit()
        return cur.rowcount > 0


async def set_raid_active(name: str, is_active: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE raids_data SET is_active=? WHERE name=?",
            (int(is_active), name),
        )
        await db.commit()
        return cur.rowcount > 0


async def set_raid_period(name: str, from_iso: str | None, until_iso: str | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE raids_data SET available_from=?, available_until=? WHERE name=?",
            (from_iso, until_iso, name),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_user_extreme_slot_this_week(
    discord_id: str, party_week_key: str
) -> dict | None:
    """이번 주 익스트림 파티에 참여 중인 슬롯 반환. 없으면 None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT ps.character_name, p.raid_name, p.scheduled_datetime "
            "FROM party_slots ps "
            "JOIN parties p ON ps.party_message_id = p.message_id "
            "JOIN raids_data r ON r.name = p.raid_name "
            "JOIN raid_categories c ON c.name = r.category "
            "WHERE ps.discord_id = ? "
            "AND c.is_extreme = 1 "
            "AND p.status IN ('recruiting', 'full', 'closed')",
            (discord_id,),
        )
        rows = await cur.fetchall()
    for row in rows:
        r = dict(row)
        sdt = r.get("scheduled_datetime")
        if sdt and get_week_key_for_dt(sdt) == party_week_key:
            return r
    return None


async def get_expired_extreme_parties(now_iso: str) -> list[dict]:
    """available_until이 지난 익스트림 레이드의 활성 파티."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.* FROM parties p "
            "JOIN raids_data r ON r.name = p.raid_name "
            "JOIN raid_categories c ON c.name = r.category "
            "WHERE c.is_extreme = 1 "
            "AND r.available_until IS NOT NULL "
            "AND r.available_until < ? "
            "AND p.status IN ('recruiting', 'full', 'closed')",
            (now_iso,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── 난이도 ─────────────────────────────────────

async def add_difficulty(
    raid_name: str, difficulty: str, min_level: int,
    total_slots: int, party_split: int | None, gates: int, sort_order: int,
) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO raid_difficulties "
                "(raid_name, difficulty, min_level, total_slots, party_split, gates, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (raid_name, difficulty, min_level, total_slots, party_split, gates, sort_order),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_difficulty(raid_name: str, difficulty: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM raid_difficulties WHERE raid_name=? AND difficulty=?",
            (raid_name, difficulty),
        )
        await db.commit()
        return cur.rowcount > 0


# ── 직업 ───────────────────────────────────────

async def get_support_classes_set() -> set[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name FROM job_classes WHERE is_support=1"
        )
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def get_all_job_classes() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT name, is_support FROM job_classes ORDER BY name"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_job_class(name: str, is_support: bool) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO job_classes (name, is_support) VALUES (?, ?)",
                (name, int(is_support)),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_job_class(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM job_classes WHERE name=?", (name,))
        await db.commit()
        return cur.rowcount > 0


# ── 초기 시드 ───────────────────────────────────

async def seed_game_data() -> None:
    """테이블이 비어있을 때 기본 레이드·직업 데이터를 삽입한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM raid_categories")
        if (await cur.fetchone())[0] > 0:
            return  # 이미 시드됨

        await db.executemany(
            "INSERT OR IGNORE INTO raid_categories (name, sort_order) VALUES (?, ?)",
            [("카제로스", 0), ("그림자", 1), ("어비스", 2)],
        )
        await db.executemany(
            "INSERT OR IGNORE INTO raids_data (name, short_name, icon, category) VALUES (?, ?, ?, ?)",
            [
                ("아르모체(4막)", "4막",  "🗡️", "카제로스"),
                ("종막",         "종막", "🗡️", "카제로스"),
                ("세르카",       "세르카","🗡️", "그림자"),
                ("지평의 성당",  "지평", "🔔", "어비스"),
            ],
        )
        await db.executemany(
            "INSERT OR IGNORE INTO raid_difficulties "
            "(raid_name, difficulty, min_level, total_slots, party_split, gates, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("아르모체(4막)", "노말", 1700, 8, 4, 2, 0),
                ("아르모체(4막)", "하드", 1720, 8, 4, 2, 1),
                ("종막",         "노말", 1710, 8, 4, 2, 0),
                ("종막",         "하드", 1730, 8, 4, 2, 1),
                ("세르카",       "노말",        1700, 4, None, 2, 0),
                ("세르카",       "하드",        1730, 4, None, 2, 1),
                ("세르카",       "나이트메어",  1740, 4, None, 2, 2),
                ("지평의 성당",  "1단계", 1700, 4, None, 2, 0),
                ("지평의 성당",  "2단계", 1720, 4, None, 2, 1),
                ("지평의 성당",  "3단계", 1750, 4, None, 2, 2),
            ],
        )
        await db.executemany(
            "INSERT OR IGNORE INTO job_classes (name, is_support) VALUES (?, ?)",
            [
                ("워로드", 0), ("버서커", 0), ("디스트로이어", 0), ("홀리나이트", 1),
                ("슬레이어", 0), ("발키리", 1),
                ("배틀마스터", 0), ("인파이터", 0), ("기공사", 0), ("창술사", 0),
                ("스트라이커", 0), ("브레이커", 0),
                ("데빌헌터", 0), ("호크아이", 0), ("스카우터", 0), ("블래스터", 0),
                ("건슬링어", 0),
                ("블레이드", 0), ("데모닉", 0), ("소울이터", 0), ("리퍼", 0),
                ("아르카나", 0), ("소서리스", 0), ("서머너", 0), ("바드", 1),
                ("도화가", 1), ("기상술사", 0), ("환수사", 0),
                ("가디언나이트", 0),
            ],
        )
        await db.commit()
