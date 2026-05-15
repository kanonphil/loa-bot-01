from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 유저 목록 ─────────────────────────────────────────────

@router.get("")
async def get_users():
  async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
    conn.row_factory = __import__("aiosqlite").Row
    cur = await conn.execute(
      # registered_at DESC: 최근 등록 유저부터 정렬
      "SELECT discord_id, registered_at FROM users ORDER BY registered_at DESC"
    )
    rows = await cur.fetchall()
  return [dict(r) for r in rows]


# ── 유저 캐릭터 목록 ──────────────────────────────────────

@router.get("/{discord_id}/characters")
async def get_characters(discord_id: str):
  # max_age_hours=99999: 캐시 만료 무시하고 전체 조회
  chars = await db.get_cached_characters(discord_id, max_age_hours=99999)
  return chars


# ── 유저 삭제 ─────────────────────────────────────────────

@router.delete("/{discord_id}")
async def delete_user(discord_id: str):
  # delete_user: 기존 manager.py의 함수 재사용
  await db.delete_user(discord_id)
  return {"success": True}