"""관리자 탭 — 1단계: 카테고리/레이드/난이도/직업 CRUD.

카테고리/레이드/난이도는 서로 계층 관계(카테고리 → 레이드 → 난이도)라 한 페이지
안의 탭(쿼리 파라미터 기반, party_list.html/ranking.html과 같은 패턴)으로 묶여있다.
직업은 그 계층과 무관한 별개 데이터(딜러/서포터 분류만 씀)라 /admin/classes로
완전히 분리한다 — 사용자가 "레이드 관리에 왜 직업이 껴있냐"고 명시적으로 지적했다.

실제 실행 권한 검증(discord_id가 ADMIN_DISCORD_IDS에 있는지)은 매 요청마다 봇 서버가
다시 한다(bot/api/routes/internal.py의 _require_admin) — require_admin은 화면을
숨기는 용도일 뿐이다."""
import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse

from webapp import config
from webapp.auth.dependencies import require_admin
from webapp.clients import bot_client
from webapp.format import party_view
from webapp.templating import templates

router = APIRouter()

TABS = [
    ("categories", "카테고리"),
    ("raids", "레이드"),
    ("difficulties", "난이도"),
]
_TAB_KEYS = {key for key, _ in TABS}


def _redirect(fallback_reason: str, result: dict, path: str) -> RedirectResponse:
    if not result.get("success"):
        reason = quote(result.get("reason") or fallback_reason)
        sep = "&" if "?" in path else "?"
        return RedirectResponse(f"{path}{sep}error={reason}", status_code=303)
    return RedirectResponse(path, status_code=303)


# ── 레이드 관리 화면 (카테고리/레이드/난이도 탭) ─────────────

@router.get("/admin/raids")
async def admin_raids_page(
    request: Request, tab: str | None = None, error: str | None = None,
    raid: str | None = None, user: dict = Depends(require_admin),
):
    if tab not in _TAB_KEYS:
        tab = "difficulties" if raid else "raids"

    categories, raids = await asyncio.gather(
        bot_client.get_raid_categories(),
        bot_client.get_raids(),
    )
    grouped = [
        {
            "category": c,
            "raids": sorted(
                (
                    {"name": name, **info}
                    for name, info in raids.items()
                    if info["category"] == c["name"]
                ),
                key=lambda r: r.get("sort_order", 0),
            ),
        }
        for c in categories
    ]
    selected_raid = raid if raid in raids else None
    return templates.TemplateResponse(
        request,
        "admin_raids.html",
        {
            "user": user,
            "active": "admin",
            "tabs": TABS,
            "tab": tab,
            "categories": categories,
            "grouped": grouped,
            "raids": raids,
            "raid_names": sorted(raids.keys()),
            "error": error,
            "selected_raid": selected_raid,
        },
    )


@router.post("/admin/raids/categories/add")
async def add_category(
    name: str = Form(...), sort_order: int = Form(0), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_add_category(user["discord_id"], name.strip(), sort_order)
    return _redirect(
        "카테고리를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, "/admin/raids?tab=categories",
    )


@router.post("/admin/raids/categories/delete")
async def delete_category(name: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_category(user["discord_id"], name)
    return _redirect("카테고리를 삭제하지 못했습니다.", result, "/admin/raids?tab=categories")


@router.post("/admin/raids/categories/extreme")
async def set_category_extreme(
    name: str = Form(...), is_extreme: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_category_extreme(user["discord_id"], name, is_extreme)
    return _redirect("변경하지 못했습니다.", result, "/admin/raids?tab=categories")


@router.post("/admin/raids/add")
async def add_raid(
    name: str = Form(...), short_name: str = Form(...), icon: str = Form("⚔️"),
    category: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_add_raid(
        user["discord_id"], name.strip(), short_name.strip(), icon.strip() or "⚔️", category,
    )
    return _redirect(
        "레이드를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, "/admin/raids?tab=raids",
    )


@router.post("/admin/raids/delete")
async def delete_raid(name: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_raid(user["discord_id"], name)
    return _redirect("레이드를 삭제하지 못했습니다.", result, "/admin/raids?tab=raids")


@router.post("/admin/raids/active")
async def set_raid_active(
    name: str = Form(...), is_active: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_active(user["discord_id"], name, is_active)
    return _redirect("변경하지 못했습니다.", result, "/admin/raids?tab=raids")


@router.post("/admin/raids/pin")
async def set_raid_pinned(
    name: str = Form(...), is_pinned: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_pinned(user["discord_id"], name, is_pinned)
    return _redirect("변경하지 못했습니다.", result, "/admin/raids?tab=raids")


@router.post("/admin/raids/difficulties/add")
async def add_difficulty(
    raid_name: str = Form(...), difficulty: str = Form(...),
    min_level: int = Form(...), total_slots: int = Form(...),
    party_split: str = Form(""), gates: int = Form(1),
    user: dict = Depends(require_admin),
):
    split = int(party_split) if party_split.strip() else None
    result = await bot_client.admin_add_difficulty(
        user["discord_id"], raid_name, difficulty.strip(), min_level, total_slots, split, gates,
    )
    return _redirect(
        "난이도를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result,
        f"/admin/raids?tab=difficulties&raid={quote(raid_name)}",
    )


@router.post("/admin/raids/difficulties/delete")
async def delete_difficulty(
    raid_name: str = Form(...), difficulty: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_delete_difficulty(user["discord_id"], raid_name, difficulty)
    return _redirect(
        "난이도를 삭제하지 못했습니다.", result, f"/admin/raids?tab=difficulties&raid={quote(raid_name)}",
    )


# ── 직업 관리 화면 (레이드 관리와 무관한 별도 페이지) ─────────

@router.get("/admin/classes")
async def admin_classes_page(
    request: Request, error: str | None = None, user: dict = Depends(require_admin),
):
    job_classes = await bot_client.get_job_classes()
    return templates.TemplateResponse(
        request,
        "admin_classes.html",
        {
            "user": user,
            "active": "admin_classes",
            "job_classes": sorted(job_classes, key=lambda c: c["name"]),
            "error": error,
        },
    )


@router.post("/admin/classes/add")
async def add_class(
    name: str = Form(...), is_support: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_add_class(user["discord_id"], name.strip(), is_support)
    return _redirect("직업을 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, "/admin/classes")


@router.post("/admin/classes/delete")
async def delete_class(name: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_class(user["discord_id"], name)
    return _redirect("직업을 삭제하지 못했습니다.", result, "/admin/classes")


# ── 공대 관리 (진행 중 + 종료됨 전체 조회, 액션은 각 공대 상세 페이지에서) ──
# 강제 마감/재개/강퇴/위임/일정변경 버튼은 여기 새로 안 만든다 — /parties/{id}
# 상세 페이지의 "파티장 관리" 패널이 관리자에게도 그대로 열리므로(_detail_context의
# is_leader가 관리자를 포함하도록 바뀜), 이 목록은 "찾아서 들어가는" 용도로 충분하다.
# 클리어 되돌리기만 관리자 전용이라 상세 페이지에 별도 패널로 있다.

def _closed_status_view(entry: dict) -> dict:
    label, tone = ("클리어", "ok") if entry["status"] == "disbanded" else (entry["status"], "")
    leader_slot = next((s for s in entry.get("slots") or [] if s["discord_id"] == entry["leader_id"]), None)
    return {**entry, "status_label": label, "status_tone": tone, "leader_character_name": leader_slot["character_name"] if leader_slot else None}


@router.get("/admin/parties")
async def admin_parties_page(
    request: Request, tab: str = "open", user: dict = Depends(require_admin),
):
    if tab not in ("open", "closed"):
        tab = "open"
    result = await bot_client.admin_list_parties(config.DISCORD_GUILD_ID, user["discord_id"])
    open_parties = [party_view(p) for p in result["open"]]
    closed_parties = [_closed_status_view(p) for p in result["closed"]]
    open_parties.sort(key=lambda p: (p.get("scheduled_datetime") is None, p.get("scheduled_datetime") or ""))
    closed_parties.sort(key=lambda p: p.get("created_at") or "", reverse=True)

    return templates.TemplateResponse(
        request,
        "admin_parties.html",
        {
            "user": user,
            "active": "admin_parties",
            "tab": tab,
            "open_parties": open_parties,
            "closed_parties": closed_parties,
        },
    )
