from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db
from bot.data import raids as raids_module

# dependencies=[Depends(verify_api_key)]: 이 라우터의 모든 엔드포인트에 자동으로 인증 적용
router = APIRouter(dependencies=[Depends(verify_api_key)])

# ── 카테고리 ─────────────────────────────────────────────

@router.get("/categories")
async def get_categories():
  return await db.get_categories()

@router.post("/categories")
async def add_category(name: str, sort_order: int):
  added = await db.add_category(name, sort_order)
  # raids_module.reload(): DB 수정 후 봇 캐시 즉시 갱신
  await raids_module.reload()
  return {"success": added}

@router.delete("/categories/{name}")
async def delete_category(name: str):
  removed = await db.remove_category(name)
  await raids_module.reload()
  return {"success": removed}

# ── 레이드 ───────────────────────────────────────────────

@router.get("")
async def get_raids():
  # raids_module.RAIDS: DB 재조회 없이 메모리 캐시에서 바로 반환
  return raids_module.RAIDS

@router.delete("/{raid_name}")
async def delete_raid(raid_name: str):
  removed = await db.remove_raid(raid_name)
  await raids_module.reload()
  return {"success": removed}

# ── 난이도 ───────────────────────────────────────────────

@router.get("/{raid_name}/difficulties")
async def get_difficulties(raid_name: str):
  raid = raids_module.RAIDS.get(raid_name)
  if not raid:
    return []
  return raid["difficulties"]

@router.delete("/{raid_name}/difficulties/{difficulty}")
async def delete_difficulty(raid_name: str, difficulty: str):
  removed = await db.remove_difficulty(raid_name, difficulty)
  await raids_module.reload()
  return {"success": removed}