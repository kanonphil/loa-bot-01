"""봇 상태 요약 — 관리자 API(/api/status)와 웹 관리자(/api/internal/admin/status)가 공유."""
import time

import aiosqlite

from bot.api import bot_ref
import bot.database.manager as db


async def collect_status() -> dict:
  bot = bot_ref.get_bot()
  uptime_sec = int(time.time() - bot_ref.start_time)
  is_online = bot is not None and bot.is_ready()

  async with aiosqlite.connect(db.DB_PATH) as conn:
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    user_count = (await cur.fetchone())[0]
    cur = await conn.execute(
      "SELECT COUNT(*) FROM parties WHERE status IN ('recruiting','full','closed')"
    )
    active_party_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM raid_subscriptions")
    sub_count = (await cur.fetchone())[0]

  h, rem = divmod(uptime_sec, 3600)
  m, s = divmod(rem, 60)
  return {
    "is_online":          is_online,
    "uptime_seconds":     uptime_sec,
    "uptime_str":         f"{h}시간 {m}분 {s}초",
    "user_count":         user_count,
    "active_party_count": active_party_count,
    "subscription_count": sub_count,
    "latency_ms":         round(bot.latency * 1000, 1) if bot and is_online else None,
  }
