import json
import os
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import encrypt_api_key, decrypt_api_key, is_plaintext_key

# LOA_DB_PATH로 덮어쓸 수 있음 — 로컬 테스트 시 운영 DB(loa_bot.db)와 분리하는 용도.
DB_PATH = os.environ.get("LOA_DB_PATH", "loa_bot.db")
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

CREATE TABLE IF NOT EXISTS user_api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id  TEXT NOT NULL,
    label       TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    added_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_api_keys_discord_id
    ON user_api_keys(discord_id);

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

-- 완료(클리어)/취소된 파티가 purge_party로 지워지기 직전에 남기는 이력.
-- 주간 리셋 때 parties/party_slots에서는 완전히 삭제되지만, 여기는 계속 보관된다
-- (캘린더/통계에서 지난달 이전 기록도 조회할 수 있어야 하기 때문).
CREATE TABLE IF NOT EXISTS party_history (
    message_id          TEXT PRIMARY KEY,
    guild_id            TEXT,
    leader_id           TEXT,
    raid_name           TEXT,
    difficulty          TEXT,
    proficiency         TEXT,
    scheduled_time      TEXT,
    scheduled_datetime  TEXT,
    total_slots         INTEGER,
    min_level           INTEGER,
    status              TEXT,
    memo                TEXT,
    created_at          TIMESTAMP,
    slot_count          INTEGER,
    slots_json          TEXT,
    archived_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- 레이드 체크에서 캐릭터별로 "이 레이드만 보이게" 고른 선택 상태.
-- _state에 행이 없으면 "커스터마이즈 안 함"(입장 가능한 레이드 전체 표시, 기존 동작),
-- _state에 행이 있으면 character_raid_selection에 담긴 레이드만 표시한다
-- (전부 해제해서 0개를 선택한 상태와, 애초에 선택한 적이 없는 상태를 구분하기 위해 테이블을 분리).
CREATE TABLE IF NOT EXISTS character_raid_selection_state (
    discord_id      TEXT,
    character_name  TEXT,
    PRIMARY KEY (discord_id, character_name)
);

CREATE TABLE IF NOT EXISTS character_raid_selection (
    discord_id      TEXT,
    character_name  TEXT,
    raid_name       TEXT,
    PRIMARY KEY (discord_id, character_name, raid_name)
);

CREATE TABLE IF NOT EXISTS raid_subscriptions (
    discord_id  TEXT,
    raid_name   TEXT,
    difficulty  TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, raid_name, difficulty)
);

CREATE TABLE IF NOT EXISTS party_invites (
    message_id  TEXT,
    discord_id  TEXT,
    slot_number INTEGER NOT NULL DEFAULT 0,
    invited_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id, discord_id)
);

CREATE TABLE IF NOT EXISTS user_preferences (
    discord_id        TEXT PRIMARY KEY,
    pre_notify_hours  REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS notification_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id  TEXT NOT NULL,
    raid_name   TEXT NOT NULL,
    difficulty  TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS party_pre_notifications (
    message_id  TEXT,
    discord_id  TEXT,
    PRIMARY KEY (message_id, discord_id)
);

-- 길드 커뮤니티 게시판 (레이드 공대 모집과는 별개 — 이벤트/공지/자유 게시글).
CREATE TABLE IF NOT EXISTS board_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id            TEXT NOT NULL,
    author_discord_id   TEXT NOT NULL,
    title               TEXT NOT NULL,
    category            TEXT NOT NULL,   -- '이벤트' | '공지' | '자유'
    content             TEXT NOT NULL,
    scheduled_datetime  TEXT,            -- ISO 8601 KST offset 문자열, nullable (공지/자유는 일정 없어도 됨)
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    announced           INTEGER NOT NULL DEFAULT 0,   -- 이벤트 카테고리 디스코드 알림 발송 여부 (중복 발송 방지)
    reminder_10min_sent INTEGER NOT NULL DEFAULT 0,
    reminder_start_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS board_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS board_participants (
    post_id    INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id, discord_id)
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
            ("api_key_id",      "INTEGER"),
            ("combat_power",    "INTEGER"),   # 전투력 랭킹용 — 아머리 조회로 갱신
            ("combat_power_at", "TIMESTAMP"),
        ]:
            try:
                await db.execute(f"ALTER TABLE user_characters ADD COLUMN {col} {definition}")
            except Exception:
                pass
        try:
            await db.execute("ALTER TABLE party_invites ADD COLUMN slot_number INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE parties ADD COLUMN pre_notified INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE parties ADD COLUMN extreme_period_notified INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        for col, definition in [
            ("board_channel_id", "TEXT"),
            ("board_role_id",    "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await db.commit()
    await seed_game_data()
    await _migrate_encrypt_api_keys()
    await _migrate_backfill_user_api_keys()


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


async def set_board_channel(guild_id: str, channel_id: str, role_id: str | None) -> None:
    """게시판 이벤트 알림을 올릴 채널/멘션할 역할 설정. INSERT 시 forum_channel_id는
    NULL로 두어 기존에 설정된 값이 있어도 UPSERT가 그 값을 건드리지 않게 한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guild_settings (guild_id, board_channel_id, board_role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET board_channel_id=excluded.board_channel_id, "
            "board_role_id=excluded.board_role_id",
            (guild_id, channel_id, role_id),
        )
        await db.commit()


async def get_board_settings(guild_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT board_channel_id, board_role_id FROM guild_settings WHERE guild_id=?",
            (guild_id,),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


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


async def _migrate_backfill_user_api_keys() -> None:
    """부계정 기능 배포 이전에 등록한 유저는 키가 users.loa_api_key에만 있고
    user_api_keys에는 없어서, list_user_api_keys가 빈 목록을 반환해 /원정대 등에서
    "등록 안 됨"으로 잘못 처리되던 문제. user_api_keys가 하나도 없는 유저만
    레거시 키를 그대로 옮겨 채운다(1회성, 이미 있으면 건드리지 않아 새 가입자와 무관)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT discord_id, loa_api_key, registered_at FROM users")
        users_rows = await cur.fetchall()

        migrated = 0
        for row in users_rows:
            discord_id = row["discord_id"]
            existing = await (await db.execute(
                "SELECT 1 FROM user_api_keys WHERE discord_id=? LIMIT 1", (discord_id,)
            )).fetchone()
            if existing:
                continue  # 이미 부계정 테이블에 있음 — 새 가입자거나 이미 마이그레이션됨

            char_row = await (await db.execute(
                "SELECT character_name FROM user_characters WHERE discord_id=? ORDER BY added_at LIMIT 1",
                (discord_id,),
            )).fetchone()
            label = char_row["character_name"] if char_row else "기본 계정"

            insert_cur = await db.execute(
                "INSERT INTO user_api_keys (discord_id, label, api_key, added_at) VALUES (?, ?, ?, ?)",
                (discord_id, label, row["loa_api_key"], row["registered_at"]),
            )
            await db.execute(
                "UPDATE user_characters SET api_key_id=? WHERE discord_id=? AND api_key_id IS NULL",
                (insert_cur.lastrowid, discord_id),
            )
            migrated += 1

        if migrated > 0:
            await db.commit()
            print(f"[DB] user_api_keys 백필 마이그레이션 완료: {migrated}명")


async def delete_user(discord_id: str) -> None:
    """유저 데이터 전체 삭제 (관리자용). user_api_keys(부계정 포함)도 함께 정리해
    고아 row가 남지 않도록 한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users          WHERE discord_id=?", (discord_id,))
        await db.execute("DELETE FROM user_characters WHERE discord_id=?", (discord_id,))
        await db.execute("DELETE FROM user_preferences WHERE discord_id=?", (discord_id,))
        await db.execute("DELETE FROM user_api_keys    WHERE discord_id=?", (discord_id,))
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


async def user_exists(discord_id: str) -> bool:
    """discord_id가 /api등록을 마쳐 users 테이블에 있는지만 확인 (복호화 없이 가볍게)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM users WHERE discord_id=?", (discord_id,)
        )
        row = await cur.fetchone()
    return row is not None


# ──────────────────────────────────────────────
# 유저별 다중 API 키 (부계정 지원)
# ──────────────────────────────────────────────

async def add_user_api_key(discord_id: str, label: str, api_key: str) -> int:
    """새 계정(API 키)을 등록. 이 discord_id의 첫 계정이면 레거시 users.loa_api_key에도 미러링.
    반환: 새로 생성된 user_api_keys.id"""
    now = datetime.now(KST).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO user_api_keys (discord_id, label, api_key, added_at) VALUES (?, ?, ?, ?)",
            (discord_id, label, encrypt_api_key(api_key), now),
        )
        new_id = cur.lastrowid
        await db.commit()

    existing = await list_user_api_keys(discord_id)
    if len(existing) == 1:
        # 이 discord_id의 첫 계정 — 레거시 단일 키 컬럼도 함께 채워 기존 호출부 호환 유지
        await set_user_api_key(discord_id, api_key)

    return new_id


async def list_user_api_keys(discord_id: str) -> list[dict]:
    """등록된 계정 목록 (복호화된 키는 포함하지 않음)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, label, added_at FROM user_api_keys WHERE discord_id=? ORDER BY added_at",
            (discord_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_user_api_key_by_id(key_id: int) -> Optional[str]:
    """복호화된 API 키 반환 — 로스트아크 API 호출용 (내부 전용)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT api_key FROM user_api_keys WHERE id=?", (key_id,)
        )
        row = await cur.fetchone()
    return decrypt_api_key(row[0]) if row else None


async def remove_user_api_key(discord_id: str, key_id: int) -> bool:
    """계정(API 키) 삭제. 해당 키를 쓰던 캐릭터의 api_key_id는 NULL로 남긴다(캐릭터 자체는 삭제하지 않음).
    삭제한 키가 레거시 users.loa_api_key로 미러링돼 있었다면, 남은 키 중 하나로 승격하거나(없으면) 비운다."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT api_key FROM user_api_keys WHERE id=? AND discord_id=?",
            (key_id, discord_id),
        )
        row = await cur.fetchone()
        if not row:
            return False
        removed_key_encrypted = row[0]

        await db.execute(
            "UPDATE user_characters SET api_key_id=NULL WHERE api_key_id=?", (key_id,)
        )
        await db.execute(
            "DELETE FROM user_api_keys WHERE id=? AND discord_id=?", (key_id, discord_id)
        )
        await db.commit()

    # 레거시 컬럼이 방금 삭제한 키를 가리키고 있었다면 다른 키로 승격하거나 비운다
    current_legacy = await get_user_api_key(discord_id)
    removed_key = decrypt_api_key(removed_key_encrypted)
    if current_legacy == removed_key:
        remaining = await list_user_api_keys(discord_id)
        if remaining:
            promoted_key = await get_user_api_key_by_id(remaining[0]["id"])
            if promoted_key:
                await set_user_api_key(discord_id, promoted_key)
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM users WHERE discord_id=?", (discord_id,))
                await db.commit()

    return True


async def get_all_api_keys() -> list[dict]:
    """모든 유저의 모든 등록 계정 — 일일 자동 동기화용. {id, discord_id, label} 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, discord_id, label FROM user_api_keys ORDER BY discord_id, added_at"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_characters_by_api_key_id(api_key_id: int) -> list[str]:
    """특정 계정(api_key_id)에 연결된 캐릭터 이름 목록."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT character_name FROM user_characters WHERE api_key_id=? ORDER BY added_at",
            (api_key_id,),
        )
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def get_character_api_key_id(discord_id: str, character_name: str) -> Optional[int]:
    """단일 캐릭터가 연결된 api_key_id 조회. 없으면(레거시 데이터) None."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT api_key_id FROM user_characters WHERE discord_id=? AND character_name=?",
            (discord_id, character_name),
        )
        row = await cur.fetchone()
    return row[0] if row and row[0] is not None else None


# ──────────────────────────────────────────────
# 캐릭터 등록
# ──────────────────────────────────────────────

async def add_character(discord_id: str, character_name: str, api_key_id: int | None = None) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO user_characters (discord_id, character_name, api_key_id) VALUES (?, ?, ?)",
                (discord_id, character_name, api_key_id),
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


async def update_character_combat_power(discord_id: str, character_name: str, combat_power: int) -> None:
    """전투력 캐시 갱신 (랭킹용). 아머리 조회로 얻은 값을 저장한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_characters SET combat_power=?, combat_power_at=CURRENT_TIMESTAMP "
            "WHERE discord_id=? AND character_name=?",
            (int(combat_power), discord_id, character_name),
        )
        await db.commit()


async def get_expedition_ranking(metric: str, limit: int = 100) -> list[dict]:
    """전체 원정대(모든 유저의 모든 캐릭터) 랭킹.
    metric: 'combat_power' | 'item_level' | 'weekly_clears'.
    반환 각 항목: discord_id, character_name, character_class, value(정렬 기준값),
    item_level, combat_power(참고 표시용)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if metric == "weekly_clears":
            week = get_week_key()
            cur = await db.execute(
                "SELECT c.discord_id, c.character_name, uc.character_class, uc.item_level, "
                "uc.combat_power, COUNT(*) AS value "
                "FROM raid_completions c "
                "LEFT JOIN user_characters uc "
                "  ON uc.discord_id=c.discord_id AND uc.character_name=c.character_name "
                "WHERE c.week_key=? "
                "GROUP BY c.discord_id, c.character_name "
                "ORDER BY value DESC, uc.item_level DESC "
                "LIMIT ?",
                (week, limit),
            )
        else:
            column = "combat_power" if metric == "combat_power" else "item_level"
            cur = await db.execute(
                f"SELECT discord_id, character_name, character_class, item_level, combat_power, "
                f"{column} AS value FROM user_characters "
                f"WHERE {column} IS NOT NULL AND {column} > 0 "
                f"ORDER BY value DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_character_cache(
    discord_id: str, character_name: str, item_level: float, character_class: str,
    api_key_id: int | None = None,
) -> None:
    """캐릭터 캐시 갱신. api_key_id를 넘기면 해당 캐릭터가 어느 계정 소속인지도 함께 기록한다
    (None이면 기존 값 유지 — 매번 새로 조회하지 않는 호출부와 호환)."""
    async with aiosqlite.connect(DB_PATH) as db:
        if api_key_id is not None:
            await db.execute(
                "UPDATE user_characters SET item_level=?, character_class=?, "
                "cached_at=CURRENT_TIMESTAMP, api_key_id=? "
                "WHERE discord_id=? AND character_name=?",
                (item_level, character_class, api_key_id, discord_id, character_name),
            )
        else:
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


async def get_cached_characters_with_account(discord_id: str, max_age_hours: int = 6) -> list[dict]:
    """캐시된 캐릭터 목록 + 소속 계정 라벨(account_label). 웹 원정대 페이지에서
    계정별로 묶어 보여주는 용도. 계정 정보가 없는(레거시) 캐릭터는 account_label=None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT uc.character_name, uc.character_class, "
            "CASE WHEN uc.cached_at >= datetime('now', ?) THEN uc.item_level ELSE NULL END AS item_level, "
            "uc.api_key_id, k.label AS account_label "
            "FROM user_characters uc "
            "LEFT JOIN user_api_keys k ON k.id = uc.api_key_id "
            "WHERE uc.discord_id=? ORDER BY uc.added_at",
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
            # 레이드 하나당 이번 주에 인정되는 난이도는 1개뿐 — 다른 난이도로
            # 새로 체크하면 그 레이드의 기존 체크는 자동으로 대체된다.
            await db.execute(
                "DELETE FROM raid_completions "
                "WHERE discord_id=? AND character_name=? AND raid_name=? AND week_key=?",
                (discord_id, character_name, raid_name, week),
            )
            await db.execute(
                "INSERT INTO raid_completions (discord_id, character_name, raid_name, difficulty, week_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (discord_id, character_name, raid_name, difficulty, week),
            )
            await db.commit()
            return True


async def get_selected_raids(discord_id: str, character_name: str) -> list[str] | None:
    """캐릭터별로 저장된 "표시할 레이드" 선택 목록. 커스터마이즈한 적이 없으면 None
    (호출 측에서 입장 가능한 레이드 전체를 보여주면 됨), 있으면 선택된 raid_name 목록
    (전부 해제했으면 빈 리스트)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM character_raid_selection_state WHERE discord_id=? AND character_name=?",
            (discord_id, character_name),
        )
        if await cur.fetchone() is None:
            return None
        cur2 = await db.execute(
            "SELECT raid_name FROM character_raid_selection WHERE discord_id=? AND character_name=?",
            (discord_id, character_name),
        )
        rows = await cur2.fetchall()
    return [r[0] for r in rows]


async def set_selected_raids(discord_id: str, character_name: str, raid_names: list[str]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO character_raid_selection_state (discord_id, character_name) VALUES (?, ?)",
            (discord_id, character_name),
        )
        await db.execute(
            "DELETE FROM character_raid_selection WHERE discord_id=? AND character_name=?",
            (discord_id, character_name),
        )
        await db.executemany(
            "INSERT INTO character_raid_selection (discord_id, character_name, raid_name) VALUES (?, ?, ?)",
            [(discord_id, character_name, raid_name) for raid_name in raid_names],
        )
        await db.commit()


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
    """is_guest: /api등록으로 users 테이블에 있는 유저가 아니면(=게스트 초대로 참여) True."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT ps.*, (u.discord_id IS NULL) AS is_guest FROM party_slots ps "
            "LEFT JOIN users u ON u.discord_id = ps.discord_id "
            "WHERE ps.party_message_id=? ORDER BY ps.slot_number",
            (message_id,),
        )
        rows = await cur.fetchall()
    result = []
    for r in rows:
        row = dict(r)
        row["is_guest"] = bool(row["is_guest"])
        result.append(row)
    return result



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
        # party_invites 예약 슬롯도 taken으로 처리 — 초대 중인 슬롯 탈취 방지
        cur = await db.execute(
            "SELECT slot_number FROM party_invites WHERE message_id=?",
            (message_id,),
        )
        taken |= {r[0] for r in await cur.fetchall()}

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

        try:
            await db.execute(
                "INSERT INTO party_slots "
                "(party_message_id, slot_number, discord_id, character_name, character_class, role) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, slot_number, discord_id, character_name, character_class, role),
            )
        except aiosqlite.IntegrityError:
            # 동시 참여 요청으로 슬롯 충돌 발생 시
            return False, 0, "다른 유저가 동시에 참여해 슬롯이 찼습니다. 다시 시도해주세요."

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


async def get_party_join_eligibility(message_id: str, discord_id: str) -> dict:
    """파티 참여 가능 여부 + 캐릭터별 필터링 결과.

    Discord의 참여하기 버튼(bot/ui/views.py PartyView._handle_join)과 웹의 참여 API가
    동일하게 사용하는 단일 검증 로직 — 두 곳에서 각자 구현하면 규칙이 어긋날 수 있으니
    반드시 이 함수를 통해서만 판단할 것.

    반환:
      {"can_join": False, "reason": "..."}
      또는
      {"can_join": True, "qualifying": [{"name","level","class"}, ...],
       "party_split": int | None, "total_slots": int,
       "gold_done": [...], "in_other_party": [...],
       "level_too_low": [{"name","level"}, ...], "no_cache": [...],
       "min_level": int}
    """
    from datetime import datetime, timedelta, timezone

    from bot.data.raids import RAIDS

    KST = timezone(timedelta(hours=9))

    party = await get_party(message_id)
    if not party or party["status"] == "disbanded":
        return {"can_join": False, "reason": "유효하지 않은 파티입니다."}
    if party["status"] == "closed":
        return {"can_join": False, "reason": "모집이 마감된 파티입니다."}
    if party["status"] == "full":
        return {"can_join": False, "reason": "파티가 이미 꽉 찼습니다."}

    party_week_key = (
        get_week_key_for_dt(party["scheduled_datetime"])
        if party.get("scheduled_datetime")
        else get_week_key()
    )

    slots = await get_party_slots(message_id)
    if any(s["discord_id"] == discord_id for s in slots):
        return {"can_join": False, "reason": "이미 파티에 참여 중입니다."}

    raid_info = RAIDS.get(party["raid_name"], {})
    if raid_info.get("is_extreme"):
        now = datetime.now(KST)
        avail_from = raid_info.get("available_from")
        avail_until = raid_info.get("available_until")
        sdt = party.get("scheduled_datetime")

        if sdt and avail_from:
            try:
                if datetime.fromisoformat(sdt) < datetime.fromisoformat(avail_from):
                    from_dt = datetime.fromisoformat(avail_from)
                    return {
                        "can_join": False,
                        "reason": f"이 공대 일정은 운영 기간 시작({from_dt.month}/{from_dt.day}) 전입니다.",
                    }
            except ValueError:
                pass

        if avail_until:
            try:
                if datetime.fromisoformat(avail_until) < now:
                    return {"can_join": False, "reason": "운영 기간이 종료된 레이드입니다."}
            except ValueError:
                pass

        extreme_slot = await get_user_extreme_slot_this_week(discord_id, party_week_key)
        if extreme_slot:
            return {
                "can_join": False,
                "reason": (
                    f"이번 주 익스트림 레이드는 **{extreme_slot['character_name']}**으로 "
                    f"이미 참여 중입니다.\n원정대당 1캐릭터만 참여할 수 있습니다."
                ),
            }

    api_key = await get_user_api_key(discord_id)
    if not api_key:
        return {"can_join": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}

    registered = await get_user_characters(discord_id)
    if not registered:
        return {"can_join": False, "reason": "먼저 /캐릭터등록으로 캐릭터를 등록해주세요."}

    min_level: int = party["min_level"]
    cached = await get_cached_characters(discord_id, max_age_hours=99999)
    cache_map = {c["character_name"]: c for c in cached}

    qualifying: list[dict] = []
    level_too_low: list[dict] = []
    no_cache: list[str] = []

    for char_name in registered:
        c = cache_map.get(char_name)
        if not c or c["item_level"] is None:
            no_cache.append(char_name)
        elif c["item_level"] < min_level:
            level_too_low.append({"name": char_name, "level": c["item_level"]})
        else:
            qualifying.append(
                {"name": char_name, "level": c["item_level"], "class": c["character_class"]}
            )

    # 골드 완료 캐릭터 필터링 — 파티 주차 기준
    gold_done: list[str] = []
    filtered = []
    for q in qualifying:
        completions = await get_completions(discord_id, q["name"], week_key=party_week_key)
        if any(k.startswith(f"{party['raid_name']}_") for k in completions):
            gold_done.append(q["name"])
        else:
            filtered.append(q)
    qualifying = filtered

    # 같은 레이드·같은 주차의 다른 공대에 이미 참여 중인 캐릭터 필터링
    already_slots = await get_user_active_slots_in_raid(
        discord_id, party["raid_name"], message_id, party_week_key=party_week_key
    )
    already_chars = {s["character_name"] for s in already_slots}
    in_other_party: list[str] = []
    filtered2 = []
    for q in qualifying:
        if q["name"] in already_chars:
            in_other_party.append(q["name"])
        else:
            filtered2.append(q)
    qualifying = filtered2

    party_split = (raid_info.get("difficulties") or {}).get(party["difficulty"], {}).get(
        "party_split"
    )

    return {
        "can_join": True,
        "qualifying": qualifying,
        "party_split": party_split,
        "total_slots": party["total_slots"],
        "gold_done": gold_done,
        "in_other_party": in_other_party,
        "level_too_low": level_too_low,
        "no_cache": no_cache,
        "min_level": min_level,
    }


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
    """일정 변경. notified·pre_notified 모두 리셋하여 새 시각에 알림이 재발송된다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET scheduled_time=?, scheduled_datetime=?, "
            "notified=0, pre_notified=0 WHERE message_id=?",
            (scheduled_time, scheduled_datetime, message_id),
        )
        await db.execute(
            "DELETE FROM party_pre_notifications WHERE message_id=?", (message_id,)
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


async def purge_party(message_id: str, archived_status: str | None = None) -> None:
    """파티·슬롯·대기열·알림 기록을 완전히 삭제하기 전에 party_history에 이력을 남긴다.
    archived_status를 넘기면 그 값으로 기록(예: 취소 흐름에서 "cancelled"), 안 넘기면
    파티의 현재 status 그대로 남긴다(예: 주간 리셋 때 정리되는 클리어된 파티는 "disbanded")."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM parties WHERE message_id=?", (message_id,))
        party = await cur.fetchone()
        if party is not None:
            party = dict(party)
            slots_cur = await db.execute(
                "SELECT discord_id, character_name, character_class, role "
                "FROM party_slots WHERE party_message_id=? ORDER BY slot_number",
                (message_id,),
            )
            slots = [dict(r) for r in await slots_cur.fetchall()]
            await db.execute(
                "INSERT OR REPLACE INTO party_history "
                "(message_id, guild_id, leader_id, raid_name, difficulty, proficiency, "
                " scheduled_time, scheduled_datetime, total_slots, min_level, status, memo, "
                " created_at, slot_count, slots_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    party["message_id"], party["guild_id"], party["leader_id"],
                    party["raid_name"], party["difficulty"], party["proficiency"],
                    party["scheduled_time"], party["scheduled_datetime"],
                    party["total_slots"], party["min_level"],
                    archived_status or party["status"], party["memo"],
                    party["created_at"], len(slots), json.dumps(slots, ensure_ascii=False),
                ),
            )
        await db.execute("DELETE FROM party_slots             WHERE party_message_id=?", (message_id,))
        await db.execute("DELETE FROM party_waitlist          WHERE party_message_id=?", (message_id,))
        await db.execute("DELETE FROM party_pre_notifications WHERE message_id=?",       (message_id,))
        await db.execute("DELETE FROM party_invites           WHERE message_id=?",       (message_id,))
        await db.execute("DELETE FROM parties                 WHERE message_id=?",       (message_id,))
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


async def get_calendar_parties(guild_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """일정 캘린더용 — [start_iso, end_iso) 구간에 scheduled_datetime이 있는 파티 전체.
    현재 진행 중/최근에 끝난 파티(parties 테이블)와, 주간 리셋 등으로 이미 purge된
    지난 이력(party_history 테이블)을 합쳐서 반환한다 — 그래야 지난달 이전 기록도 보인다.
    취소된 파티(status='cancelled')는 party_history에 남지만, 실제 진행되지 않은 일정이라
    캘린더에는 굳이 보여주지 않는다."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT message_id, raid_name, difficulty, proficiency, scheduled_time, "
            "scheduled_datetime, total_slots, min_level, status, slot_count FROM ("
            "  SELECT p.message_id, p.raid_name, p.difficulty, p.proficiency, p.scheduled_time, "
            "         p.scheduled_datetime, p.total_slots, p.min_level, p.status, "
            "         (SELECT COUNT(*) FROM party_slots s WHERE s.party_message_id = p.message_id) AS slot_count "
            "  FROM parties p WHERE p.guild_id = ? "
            "  UNION ALL "
            "  SELECT h.message_id, h.raid_name, h.difficulty, h.proficiency, h.scheduled_time, "
            "         h.scheduled_datetime, h.total_slots, h.min_level, h.status, h.slot_count "
            "  FROM party_history h WHERE h.guild_id = ? AND h.status != 'cancelled' "
            ") combined "
            "WHERE scheduled_datetime IS NOT NULL AND scheduled_datetime >= ? AND scheduled_datetime < ? "
            "ORDER BY scheduled_datetime ASC",
            (guild_id, guild_id, start_iso, end_iso),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_disbanded_parties(guild_id: str, limit: int = 50) -> list[dict]:
    """disbanded(클리어) 파티 이력 (최신순). 주간 리셋으로 이미 purge된 지난 이력은
    party_history에서, 아직 살아있는(이번 주) 것은 parties에서 가져와 합친다."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT message_id, channel_id, guild_id, leader_id, raid_name, difficulty, proficiency, "
            "scheduled_time, scheduled_datetime, total_slots, min_level, status, notified, memo, "
            "created_at, slot_count FROM ("
            "  SELECT p.message_id, p.channel_id, p.guild_id, p.leader_id, p.raid_name, p.difficulty, "
            "         p.proficiency, p.scheduled_time, p.scheduled_datetime, p.total_slots, p.min_level, "
            "         p.status, p.notified, p.memo, p.created_at, "
            "         (SELECT COUNT(*) FROM party_slots s WHERE s.party_message_id = p.message_id) AS slot_count "
            "  FROM parties p WHERE p.guild_id=? AND p.status='disbanded' "
            "  UNION ALL "
            "  SELECT h.message_id, NULL, h.guild_id, h.leader_id, h.raid_name, h.difficulty, "
            "         h.proficiency, h.scheduled_time, h.scheduled_datetime, h.total_slots, h.min_level, "
            "         h.status, NULL, h.memo, h.created_at, h.slot_count "
            "  FROM party_history h WHERE h.guild_id=? AND h.status='disbanded'"
            ") combined "
            "ORDER BY created_at DESC LIMIT ?",
            (guild_id, guild_id, limit),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_completion(
    discord_id: str, character_name: str, raid_name: str, difficulty: str, week_key: str
) -> bool:
    """레이드 클리어 수동 추가."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO raid_completions "
                "(discord_id, character_name, raid_name, difficulty, week_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (discord_id, character_name, raid_name, difficulty, week_key),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_completion(
    discord_id: str, character_name: str, raid_name: str, difficulty: str, week_key: str
) -> bool:
    """레이드 클리어 수동 삭제."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM raid_completions "
            "WHERE discord_id=? AND character_name=? AND raid_name=? AND difficulty=? AND week_key=?",
            (discord_id, character_name, raid_name, difficulty, week_key),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_weekly_activity(guild_id: str) -> list[dict]:
    """서버의 주차별 파티 생성 수."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT strftime('%Y-%W', created_at) AS week, COUNT(*) AS count "
            "FROM parties WHERE guild_id=? "
            "GROUP BY week ORDER BY week DESC LIMIT 12",
            (guild_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_popular_raids(guild_id: str) -> list[dict]:
    """서버의 레이드별 공대 생성 수 (전체 기간)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT raid_name, difficulty, COUNT(*) AS count "
            "FROM parties WHERE guild_id=? "
            "GROUP BY raid_name, difficulty ORDER BY count DESC LIMIT 10",
            (guild_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_active_users(guild_id: str) -> list[dict]:
    """서버에서 파티에 참여한 유저 수 (주차별)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT COUNT(DISTINCT ps.discord_id) AS user_count "
            "FROM party_slots ps JOIN parties p ON ps.party_message_id = p.message_id "
            "WHERE p.guild_id=? AND p.status != 'disbanded'",
            (guild_id,),
        )
        row = await cur.fetchone()
    return dict(row) if row else {"user_count": 0}


async def create_invite(message_id: str, discord_id: str, slot_number: int) -> bool:
    """초대 생성. 중복이면 False."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO party_invites (message_id, discord_id, slot_number) VALUES (?, ?, ?)",
                (message_id, discord_id, slot_number),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def delete_invite(message_id: str, discord_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM party_invites WHERE message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        await db.commit()


async def get_reserved_slots(message_id: str) -> dict[int, str]:
    """예약된 슬롯 번호 → discord_id 맵 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT slot_number, discord_id FROM party_invites WHERE message_id=?",
            (message_id,),
        )
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def assign_invite_slot(
    message_id: str, discord_id: str,
    character_name: str, character_class: str, role: str,
) -> tuple[bool, str]:
    """예약된 슬롯에 직접 배정. (success, message)"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 예약 슬롯 번호 조회
        cur = await db.execute(
            "SELECT slot_number FROM party_invites WHERE message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        row = await cur.fetchone()
        if not row:
            return False, "초대 정보를 찾을 수 없습니다."
        slot_number = row[0]

        # 이미 해당 슬롯에 누군가 있으면 실패
        cur = await db.execute(
            "SELECT 1 FROM party_slots WHERE party_message_id=? AND slot_number=?",
            (message_id, slot_number),
        )
        if await cur.fetchone():
            return False, "이미 점유된 슬롯입니다."

        # 이미 파티에 참여 중이면 실패
        cur = await db.execute(
            "SELECT 1 FROM party_slots WHERE party_message_id=? AND discord_id=?",
            (message_id, discord_id),
        )
        if await cur.fetchone():
            return False, "이미 파티에 참여 중입니다."

        # 서포터 중복 체크 — 파티 분할 단위 적용
        if role == "support":
            cur = await db.execute(
                "SELECT rd.party_split FROM parties p "
                "JOIN raid_difficulties rd ON rd.raid_name=p.raid_name AND rd.difficulty=p.difficulty "
                "WHERE p.message_id=?",
                (message_id,),
            )
            split_row  = await cur.fetchone()
            party_split_val = split_row[0] if split_row else None
            if party_split_val:
                sub_idx = (slot_number - 1) // party_split_val
                rng_start = sub_idx * party_split_val + 1
                rng_end   = rng_start + party_split_val
                cur = await db.execute(
                    "SELECT COUNT(*) FROM party_slots "
                    "WHERE party_message_id=? AND slot_number >= ? AND slot_number < ? AND role='support'",
                    (message_id, rng_start, rng_end),
                )
                if (await cur.fetchone())[0] >= 1:
                    return False, f"이미 {sub_idx + 1}파티에 서포터가 있습니다."
            else:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM party_slots WHERE party_message_id=? AND role='support'",
                    (message_id,),
                )
                if (await cur.fetchone())[0] >= 1:
                    return False, "이미 서포터가 있습니다."

        await db.execute(
            "INSERT INTO party_slots "
            "(party_message_id, slot_number, discord_id, character_name, character_class, role) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, slot_number, discord_id, character_name, character_class, role),
        )
        await db.execute(
            "DELETE FROM party_invites WHERE message_id=? AND discord_id=?",
            (message_id, discord_id),
        )

        # 파티 풀 여부 확인
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
                (message_id,),
            )
        await db.commit()
    return True, f"{slot_number}번 슬롯 배정 완료"




async def log_notification(
    discord_id: str, raid_name: str, difficulty: str, message_id: str
) -> None:
    """구독 DM 발송 이력 기록."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notification_logs (discord_id, raid_name, difficulty, message_id) "
            "VALUES (?, ?, ?, ?)",
            (discord_id, raid_name, difficulty, message_id),
        )
        await db.commit()


async def get_notification_logs(limit: int = 100) -> list[dict]:
    """알림 발송 이력 조회."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM notification_logs ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_user_party_history(discord_id: str) -> list[dict]:
  """유저의 파티 참여 이력 (최근 20개)."""
  async with aiosqlite.connect(DB_PATH) as db:
    db.row_factory = aiosqlite.Row
    cur = await db.execute(
      "SELECT DISTINCT p.raid_name, p.difficulty, p.proficiency, "
      "p.scheduled_time, p.status, p.guild_id, p.channel_id, "
      "ps.character_name, ps.role "
      "FROM parties p "
      "JOIN party_slots ps ON p.message_id = ps.party_message_id "
      "WHERE ps.discord_id = ? "
      "ORDER BY p.created_at DESC LIMIT 20",
      (discord_id,),
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
            "d.difficulty, d.min_level, d.total_slots, d.party_split, d.gates, d.sort_order "
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
                "sort_order": r["sort_order"],
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
    """available_until이 지났고 아직 기간 만료 알림이 발송되지 않은 익스트림 레이드의 활성 파티."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.* FROM parties p "
            "JOIN raids_data r ON r.name = p.raid_name "
            "JOIN raid_categories c ON c.name = r.category "
            "WHERE c.is_extreme = 1 "
            "AND r.available_until IS NOT NULL "
            "AND r.available_until < ? "
            "AND p.status IN ('recruiting', 'full', 'closed') "
            "AND (p.extreme_period_notified IS NULL OR p.extreme_period_notified = 0)",
            (now_iso,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_extreme_period_notified(message_id: str) -> None:
    """익스트림 레이드 운영 기간 만료 알림 발송 완료 표시 — 30초 루프 중복 방지."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parties SET extreme_period_notified = 1 WHERE message_id = ?",
            (message_id,),
        )
        await db.commit()


# ── 난이도 ─────────────────────────────────────

async def get_next_difficulty_sort_order(raid_name: str) -> int:
    """이 레이드에 다음 난이도를 추가할 때 쓸 sort_order(현재 최댓값+1).
    관리자 앱처럼 순서를 직접 입력받지 않는 호출부가, 매번 0을 넣어서
    입력 순서(노말→하드→나이트메어)가 가나다 순으로 뒤섞이는 걸 방지한다."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM raid_difficulties WHERE raid_name=?",
            (raid_name,),
        )
        row = await cur.fetchone()
    return row[0] + 1


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


async def update_difficulty_sort(raid_name: str, difficulty: str, sort_order: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE raid_difficulties SET sort_order=? WHERE raid_name=? AND difficulty=?",
            (sort_order, raid_name, difficulty),
        )
        await db.commit()
        return cur.rowcount > 0


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

# ──────────────────────────────────────────────
# 레이드 구독
# ──────────────────────────────────────────────

async def subscribe_raid(discord_id: str, raid_name: str, difficulty: str) -> bool:
    """구독 등록. 이미 있으면 False 반환."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO raid_subscriptions (discord_id, raid_name, difficulty) VALUES (?, ?, ?)",
                (discord_id, raid_name, difficulty),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def unsubscribe_raid(discord_id: str, raid_name: str, difficulty: str) -> bool:
    """구독 취소. 없으면 False 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM raid_subscriptions WHERE discord_id=? AND raid_name=? AND difficulty=?",
            (discord_id, raid_name, difficulty),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_user_subscriptions(discord_id: str) -> list[dict]:
    """유저의 구독 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT raid_name, difficulty, created_at FROM raid_subscriptions "
            "WHERE discord_id=? ORDER BY raid_name, difficulty",
            (discord_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_subscriptions() -> list[dict]:
    """관리자용 — 전체 구독 목록."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT discord_id, raid_name, difficulty, created_at "
            "FROM raid_subscriptions ORDER BY raid_name, difficulty, created_at"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_raid_subscribers(raid_name: str, difficulty: str) -> list[str]:
    """특정 레이드+난이도 구독자 discord_id 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT discord_id FROM raid_subscriptions WHERE raid_name=? AND difficulty=?",
            (raid_name, difficulty),
        )
        rows = await cur.fetchall()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────
# 길드 커뮤니티 게시판
# ──────────────────────────────────────────────

async def create_board_post(
    guild_id: str, author_discord_id: str, title: str, category: str,
    content: str, scheduled_datetime: str | None,
) -> int:
    """새 게시글 생성. 반환: 새로 생성된 post id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO board_posts (guild_id, author_discord_id, title, category, "
            "content, scheduled_datetime) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, author_discord_id, title, category, content, scheduled_datetime),
        )
        await db.commit()
    return cur.lastrowid


async def get_board_post(post_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM board_posts WHERE id=?", (post_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_board_posts(guild_id: str, category: str | None = None) -> list[dict]:
    """게시글 목록 (최신순). category 지정 시 해당 카테고리만.
    created_at은 초 단위라 같은 초에 여러 개가 생성되면 동점이 날 수 있어 id DESC로 tie-break."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if category:
            cur = await db.execute(
                "SELECT * FROM board_posts WHERE guild_id=? AND category=? "
                "ORDER BY created_at DESC, id DESC",
                (guild_id, category),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM board_posts WHERE guild_id=? ORDER BY created_at DESC, id DESC",
                (guild_id,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_board_post(
    post_id: int, title: str, content: str, scheduled_datetime: str | None,
) -> bool:
    """게시글 수정. 작성자 본인인지는 라우트 레이어에서 확인한다(여기서는 검사하지 않음)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE board_posts SET title=?, content=?, scheduled_datetime=? WHERE id=?",
            (title, content, scheduled_datetime, post_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_board_post(post_id: int) -> bool:
    """게시글 삭제 — 댓글/참여자도 함께 정리(이 스키마는 FK cascade가 없어 명시적으로 지운다)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM board_posts WHERE id=?", (post_id,))
        exists = await cur.fetchone()
        if not exists:
            return False
        await db.execute("DELETE FROM board_comments     WHERE post_id=?", (post_id,))
        await db.execute("DELETE FROM board_participants WHERE post_id=?", (post_id,))
        await db.execute("DELETE FROM board_posts         WHERE id=?", (post_id,))
        await db.commit()
    return True


async def add_board_comment(post_id: int, discord_id: str, content: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO board_comments (post_id, discord_id, content) VALUES (?, ?, ?)",
            (post_id, discord_id, content),
        )
        await db.commit()
    return cur.lastrowid


async def list_board_comments(post_id: int) -> list[dict]:
    """댓글 목록 (오래된 순)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM board_comments WHERE post_id=? ORDER BY created_at ASC, id ASC",
            (post_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def join_board_post(post_id: int, discord_id: str) -> bool:
    """참여 등록 (멱등). 반환: 실제로 새로 등록됐으면 True, 이미 참여 중이면 False."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO board_participants (post_id, discord_id) VALUES (?, ?)",
            (post_id, discord_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def leave_board_post(post_id: int, discord_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM board_participants WHERE post_id=? AND discord_id=?",
            (post_id, discord_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_board_participants(post_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM board_participants WHERE post_id=? ORDER BY joined_at ASC",
            (post_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_posts_due_10min_reminder(now_iso: str) -> list[dict]:
    """10분 전 리마인더 발송 대상 — 이벤트 카테고리, 아직 미발송, 시작 10분 전 시각이 지난 게시글.
    get_parties_due_notification처럼 "<=" 비교만 하고, 상한(예: 시작 시각을 이미 지나쳐도
    상관없이) 두지 않는다 — 봇이 잠깐 멈췄다 재기동해도 놓치지 않고 발송하기 위함.
    scheduled_datetime/now_iso 둘 다 KST offset(+09:00)이 붙은 ISO 문자열이라 그대로
    문자열 비교가 가능한 parties 테이블과 달리, 여기서는 "10분 전"을 계산해야 해서
    SQLite datetime()의 UTC 변환에 기대지 않고 Python에서 직접 파싱해 비교한다."""
    now = datetime.fromisoformat(now_iso)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM board_posts "
            "WHERE category = '이벤트' "
            "AND scheduled_datetime IS NOT NULL "
            "AND reminder_10min_sent = 0",
        )
        rows = await cur.fetchall()
    due = []
    for row in rows:
        r = dict(row)
        try:
            scheduled = datetime.fromisoformat(r["scheduled_datetime"])
        except ValueError:
            continue
        if scheduled - timedelta(minutes=10) <= now:
            due.append(r)
    return due


async def get_posts_due_start_reminder(now_iso: str) -> list[dict]:
    """시작 시각 리마인더 발송 대상 — 이벤트 카테고리, 아직 미발송, 시작 시각이 지난 게시글."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM board_posts "
            "WHERE category = '이벤트' "
            "AND scheduled_datetime IS NOT NULL "
            "AND scheduled_datetime <= ? "
            "AND reminder_start_sent = 0",
            (now_iso,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_board_reminder_sent(post_id: int, which: str) -> None:
    """which: '10min' | 'start'."""
    column = "reminder_10min_sent" if which == "10min" else "reminder_start_sent"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE board_posts SET {column}=1 WHERE id=?", (post_id,)
        )
        await db.commit()


async def mark_board_announced(post_id: int) -> None:
    """이벤트 게시글의 디스코드 공지 발송 처리(성공/설정 미비 여부와 무관하게 1회만 시도)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE board_posts SET announced=1 WHERE id=?", (post_id,)
        )
        await db.commit()


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
