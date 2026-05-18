from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db
import aiosqlite

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 유저 목록 ─────────────────────────────────────────────

@router.get("")
async def get_users():
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT discord_id, registered_at FROM users ORDER BY registered_at DESC"
    )
    rows = await cur.fetchall()
  return [dict(r) for r in rows]


# ── 유저 캐릭터 목록 ──────────────────────────────────────

@router.get("/{discord_id}/characters")
async def get_characters(discord_id: str):
  return await db.get_cached_characters(discord_id, max_age_hours=99999)


# ── 유저 참여 이력 ────────────────────────────────────────

@router.get("/{discord_id}/history")
async def get_party_history(discord_id: str):
  return await db.get_user_party_history(discord_id)


# ── 유저 삭제 ─────────────────────────────────────────────

@router.delete("/{discord_id}")
async def delete_user(discord_id: str):
  await db.delete_user(discord_id)
  return {"success": True}
