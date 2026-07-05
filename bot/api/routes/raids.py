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

class DifficultySortBody(BaseModel):
  sort_order: int

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
  # sort_order를 0으로 고정하면 표시 순서가 전부 동점 처리되어(가나다 순으로 보임)
  # 노말→하드→나이트메어처럼 입력한 순서가 안 지켜지는 문제가 있었다 —
  # 추가할 때마다 그 레이드의 현재 마지막 순서 다음 값을 자동으로 매긴다.
  next_sort = await db.get_next_difficulty_sort_order(raid_name)
  added = await db.add_difficulty(
    raid_name, body.difficulty, body.min_level,
    body.total_slots, body.party_split, body.gates, next_sort,
  )
  await raids_module.reload()
  return {"success": added}

@router.patch("/{raid_name}/difficulties/{difficulty}/sort")
async def sort_difficulty(raid_name: str, difficulty: str, body: DifficultySortBody):
  updated = await db.update_difficulty_sort(raid_name, difficulty, body.sort_order)
  await raids_module.reload()
  return {"success": updated}

@router.delete("/{raid_name}/difficulties/{difficulty}")
async def delete_difficulty(raid_name: str, difficulty: str):
  removed = await db.remove_difficulty(raid_name, difficulty)
  await raids_module.reload()
  return {"success": removed}


# ── 직업 ─────────────────────────────────────────────────

class JobClassBody(BaseModel):
  name: str
  is_support: bool = False

@router.get("/classes")
async def get_classes():
  return await db.get_all_job_classes()

@router.post("/classes")
async def add_class(body: JobClassBody):
  added = await db.add_job_class(body.name, body.is_support)
  await raids_module.reload()
  return {"success": added}

@router.delete("/classes/{name}")
async def delete_class(name: str):
  removed = await db.remove_job_class(name)
  await raids_module.reload()
  return {"success": removed}
