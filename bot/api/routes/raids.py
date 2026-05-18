from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
import bot.database.manager as db
from bot.data import raids as raids_module

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 요청 바디 모델 ─────────────────────────────────────────

class CategoryBody(BaseModel):
  name: str
  sort_order: int

class RaidBody(BaseModel):
  name: str
  short_name: str
  icon: str = "⚔️"
  category: str

class DifficultyBody(BaseModel):
  difficulty: str
  min_level: int
  total_slots: int
  party_split: int | None = None
  gates: int = 1

class PeriodBody(BaseModel):
  available_from: str | None = None
  available_until: str | None = None

class ActiveBody(BaseModel):
  is_active: bool

class CategorySortBody(BaseModel):
  sort_order: int

class CategoryExtremeBody(BaseModel):
  is_extreme: bool


# ── 카테고리 ─────────────────────────────────────────────

@router.get("/categories")
async def get_categories():
  return await db.get_categories()

@router.post("/categories")
async def add_category(body: CategoryBody):
  added = await db.add_category(body.name, body.sort_order)
  await raids_module.reload()
  return {"success": added}

@router.patch("/categories/{name}/sort")
async def sort_category(name: str, body: CategorySortBody):
  updated = await db.update_category_sort(name, body.sort_order)
  await raids_module.reload()
  return {"success": updated}

@router.patch("/categories/{name}/extreme")
async def set_category_extreme(name: str, body: CategoryExtremeBody):
  updated = await db.update_category_extreme(name, body.is_extreme)
  await raids_module.reload()
  return {"success": updated}

@router.delete("/categories/{name}")
async def delete_category(name: str):
  removed = await db.remove_category(name)
  await raids_module.reload()
  return {"success": removed}


# ── 레이드 ───────────────────────────────────────────────

@router.get("")
async def get_raids():
  return raids_module.RAIDS

@router.post("")
async def add_raid(body: RaidBody):
  added = await db.add_raid(body.name, body.short_name, body.icon, body.category)
  await raids_module.reload()
  return {"success": added}

@router.patch("/{raid_name}/active")
async def set_raid_active(raid_name: str, body: ActiveBody):
  updated = await db.set_raid_active(raid_name, body.is_active)
  await raids_module.reload()
  return {"success": updated}

@router.patch("/{raid_name}/period")
async def set_raid_period(raid_name: str, body: PeriodBody):
  updated = await db.set_raid_period(raid_name, body.available_from, body.available_until)
  await raids_module.reload()
  return {"success": updated}

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

@router.post("/{raid_name}/difficulties")
async def add_difficulty(raid_name: str, body: DifficultyBody):
  added = await db.add_difficulty(
    raid_name, body.difficulty, body.min_level,
    body.total_slots, body.party_split, body.gates, 0,
  )
  await raids_module.reload()
  return {"success": added}

@router.delete("/{raid_name}/difficulties/{difficulty}")
async def delete_difficulty(raid_name: str, difficulty: str):
  removed = await db.remove_difficulty(raid_name, difficulty)
  await raids_module.reload()
  return {"success": removed}
