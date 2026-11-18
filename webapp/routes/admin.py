"""관리 화면 — 레이드(마스터-디테일) · 직업 · 공대 · 유저 · 통계 · 알림·구독 · 클리어 · 작업 기록.

모든 탭이 같은 틀(admin_base.html: 제목 줄 + 봇 상태 칩 + 묶음 탭)을 쓰고, 위에 검색·필터, 아래에 표,
줄 오른쪽에 동작 버튼을 둔다. 레이드는 왼쪽에서 고르고 오른쪽에서 고치는 구조라 카테고리/레이드/난이도가
한 화면에 있다(`?raid=` 쿼리로 선택). 직업은 그 계층과 무관한 별개 데이터라 /admin/classes로 분리돼 있다.

실제 실행 권한 검증(discord_id가 ADMIN_DISCORD_IDS에 있는지)은 매 요청마다 봇 서버가
다시 한다(bot/api/routes/internal.py의 _require_admin) — require_admin은 화면을
숨기는 용도일 뿐이다."""
import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from webapp import config, notification_store, party_events
from webapp.auth.dependencies import require_admin
from webapp.clients import bot_admin, bot_client
from webapp.flash import redirect_result, redirect_with_toast
from webapp.format import is_overdue_party, party_view
from webapp.routes.party import _history_view
from webapp.templating import templates
from webapp.utils import kst_time, safe_local_path, time_ago

router = APIRouter()

KST = timezone(timedelta(hours=9))


async def _render(request: Request, template: str, user: dict, active: str, ctx: dict | None = None):
    """관리 화면 공통 렌더 — 제목 줄의 봇 상태 칩에 쓰는 bot_status를 항상 같이 싣는다."""
    status = await bot_admin.get_status(user["discord_id"])
    return templates.TemplateResponse(
        request, template, {"user": user, "active": active, "bot_status": status, **(ctx or {})},
    )


async def _safe(coro, default=None):
    """없어도 화면이 그려져야 하는 보조 데이터 — 실패하면 기본값."""
    try:
        return await coro
    except Exception:
        return default


def _parse_split(raw: str) -> tuple[int | None, str | None]:
    """파티 분할 인원 입력 — 비우면 분할 없음. 숫자가 아니면 (None, 오류문구). int()를 바로 부르면
    "abc" 한 번에 500이 났다."""
    raw = raw.strip()
    if not raw:
        return None, None
    if not (raw.isascii() and raw.isdigit()):
        return None, "파티 분할 인원은 숫자로 입력해주세요."
    return int(raw), None


def _parse_gold(raw: str) -> tuple[int | None, str | None]:
    """클리어 골드 입력 — 비우면 미입력(null). 쉼표는 허용한다(1,500)."""
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None, None
    if not (raw.isascii() and raw.isdigit()):
        return None, "클리어 골드는 0 이상의 숫자로 입력해주세요."
    return int(raw), None


def _parse_order(raw: str) -> list[str]:
    """순서 저장 폼의 hidden input — 드래그/↑↓로 만든 최종 배열을 JSON으로 받는다."""
    try:
        order = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in order] if isinstance(order, list) else []


def _period_to_iso(value: str) -> str | None:
    """datetime-local 입력(YYYY-MM-DDTHH:MM)을 디스코드 /관리 레이드기간설정과 같은
    KST 오프셋 붙은 ISO로 — 봇의 is_recruitable이 aware datetime과 비교하므로 naive로
    저장하면 비교 자체가 실패한다."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=KST).isoformat()
    except ValueError:
        return None


def _redirect(fallback_reason: str, result: dict, path: str, done: str | None = "저장했습니다.") -> RedirectResponse:
    """관리자 액션 결과 → redirect + 토스트(webapp/flash.py). 이전엔 실패만 `?error=`로 정적 문단에
    보여주고 성공은 아무 반응이 없었다."""
    return redirect_result(path, result, done, fallback_reason)


def _raids_path(raid: str | None = None) -> str:
    return f"/admin/raids?raid={quote(raid)}" if raid else "/admin/raids"


# ── 관리자 모드 토글 (사이드바 스위치 — 화면 노출만 제어, 실행 권한은 항상 유효) ──

@router.post("/admin/toggle-mode")
async def toggle_admin_mode(request: Request, user: dict = Depends(require_admin)):
    session_user = request.session["user"]
    session_user["admin_mode"] = not session_user.get("admin_mode", False)
    request.session["user"] = session_user

    # referer의 host는 신뢰하지 않고 경로만 취해 같은 사이트로만 돌려보낸다.
    referer = urlparse(request.headers.get("referer", ""))
    path = referer.path or "/main"
    if referer.query:
        path = f"{path}?{referer.query}"
    return RedirectResponse(safe_local_path(path, "/main"), status_code=303)


# ── 레이드 (마스터-디테일) ────────────────────────────────────

def _party_layout(total: int, split: int | None) -> str:
    if split and split > 0 and total and total % split == 0:
        return f"{split}인 × {total // split}파티"
    return f"{total}인 · 분할 없음" if total else "-"


def _difficulty_rows(raid: dict) -> list[dict]:
    gold = raid.get("difficulty_gold") or {}
    rows = []
    for name, d in (raid.get("difficulties") or {}).items():
        clear_gold = d.get("clear_gold", gold.get(name))
        rows.append({
            "name": name, **d, "clear_gold": clear_gold,
            "layout": _party_layout(d.get("total_slots") or 0, d.get("party_split")),
        })
    return rows


@router.get("/admin/raids")
async def admin_raids_page(
    request: Request, raid: str | None = None, user: dict = Depends(require_admin),
):
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
    selected_name = raid if raid in raids else next((r["name"] for g in grouped for r in g["raids"]), None)
    selected = None
    refs = None
    if selected_name:
        selected = {"name": selected_name, **raids[selected_name], "difficulty_rows": _difficulty_rows(raids[selected_name])}
        refs = await bot_admin.raid_references(user["discord_id"], selected_name)
    return await _render(request, "admin_raids.html", user, "admin", {
        "categories": categories,
        "grouped": grouped,
        "raid_count": len(raids),
        "selected": selected,
        "refs": refs,
        "category_raid_counts": {g["category"]["name"]: len(g["raids"]) for g in grouped},
    })


@router.post("/admin/raids/save")
async def save_raid(
    old_name: str = Form(...), name: str = Form(...), short_name: str = Form(...),
    icon: str = Form("⚔️"), category: str = Form(...), user: dict = Depends(require_admin),
):
    """기본 정보 한 번에 저장 — 이름(연쇄 변경) · 약칭 · 아이콘 · 카테고리를 바뀐 것만 봇에 보낸다."""
    uid = user["discord_id"]
    name, short_name, icon = name.strip(), short_name.strip(), icon.strip() or "⚔️"
    raids = await bot_client.get_raids()
    current = raids.get(old_name)
    if current is None:
        return redirect_with_toast(_raids_path(), "레이드를 찾지 못했습니다. 이미 이름이 바뀌었거나 삭제됐을 수 있어요.", "error")
    if not name or not short_name:
        return redirect_with_toast(_raids_path(old_name), "이름과 약칭은 비울 수 없습니다.", "error")

    current_name = old_name
    if name != old_name:
        result = await bot_client.admin_rename_raid(uid, old_name, name)
        if not result.get("success"):
            return redirect_with_toast(_raids_path(old_name), result.get("reason") or "이름을 바꾸지 못했습니다.", "error")
        if not result.get("unchanged"):
            await notification_store.rename_raid(old_name, name)
        current_name = name
    if short_name != current.get("short_name") or icon != current.get("icon"):
        result = await bot_client.admin_update_raid(uid, current_name, short_name, icon)
        if not result.get("success"):
            return redirect_with_toast(_raids_path(current_name), result.get("reason") or "약칭·아이콘을 저장하지 못했습니다.", "error")
    if category != current.get("category"):
        result = await bot_client.admin_move_raid_category(uid, current_name, category)
        if not result.get("success"):
            return redirect_with_toast(_raids_path(current_name), result.get("reason") or "카테고리를 옮기지 못했습니다.", "error")
    return redirect_with_toast(_raids_path(current_name), "저장했습니다.")


@router.post("/admin/raids/add")
async def add_raid(
    name: str = Form(...), short_name: str = Form(...), icon: str = Form("⚔️"),
    category: str = Form(...), user: dict = Depends(require_admin),
):
    name = name.strip()
    result = await bot_client.admin_add_raid(
        user["discord_id"], name, short_name.strip(), icon.strip() or "⚔️", category,
    )
    path = _raids_path(name) if result.get("success") else _raids_path()
    return _redirect("레이드를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, path, "레이드를 추가했습니다.")


@router.post("/admin/raids/delete")
async def delete_raid(name: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_raid(user["discord_id"], name)
    return _redirect("레이드를 삭제하지 못했습니다.", result, _raids_path(), "레이드를 삭제했습니다.")


@router.post("/admin/raids/active")
async def set_raid_active(
    name: str = Form(...), is_active: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_active(user["discord_id"], name, is_active)
    return _redirect("변경하지 못했습니다.", result, _raids_path(name), "활성화했습니다." if is_active else "비활성화했습니다.")


@router.post("/admin/raids/pin")
async def set_raid_pinned(
    name: str = Form(...), is_pinned: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_pinned(user["discord_id"], name, is_pinned)
    return _redirect("변경하지 못했습니다.", result, _raids_path(name), "상단에 고정했습니다." if is_pinned else "고정을 풀었습니다.")


@router.post("/admin/raids/update")
async def update_raid(
    name: str = Form(...), short_name: str = Form(...), icon: str = Form("⚔️"),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_update_raid(user["discord_id"], name, short_name.strip(), icon.strip() or "⚔️")
    return _redirect("레이드를 수정하지 못했습니다.", result, _raids_path(name))


@router.post("/admin/raids/rename")
async def rename_raid(
    old_name: str = Form(...), new_name: str = Form(...), user: dict = Depends(require_admin),
):
    new_name = new_name.strip()
    result = await bot_client.admin_rename_raid(user["discord_id"], old_name, new_name)
    if result.get("success") and not result.get("unchanged"):
        await notification_store.rename_raid(old_name, new_name)
    path = _raids_path(new_name if result.get("success") else old_name)
    return _redirect("이름을 바꾸지 못했습니다.", result, path, "이름을 바꿨습니다. 관련 기록도 함께 갱신됐습니다.")


@router.post("/admin/raids/move-category")
async def move_raid_category(
    name: str = Form(...), category: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_move_raid_category(user["discord_id"], name, category)
    return _redirect("카테고리를 옮기지 못했습니다.", result, _raids_path(name), "카테고리를 옮겼습니다.")


@router.post("/admin/raids/period")
async def set_raid_period(
    name: str = Form(...), available_from: str = Form(""), available_until: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_period(
        user["discord_id"], name, _period_to_iso(available_from), _period_to_iso(available_until),
    )
    return _redirect("운영 기간을 저장하지 못했습니다.", result, _raids_path(name))


@router.get("/admin/raids/references")
async def raid_references(
    request: Request, name: str, difficulty: str | None = None, user: dict = Depends(require_admin),
):
    """이름 변경 폼을 펼칠 때만 htmx로 조회(목록 렌더 때 레이드마다 세지 않는다)."""
    refs = await bot_client.admin_raid_references(user["discord_id"], name, difficulty or None)
    return templates.TemplateResponse(request, "_admin_raid_references.html", {"refs": refs, "difficulty": difficulty})


# 카테고리 ─ 편집 대화상자에서 쓴다. return_raid는 처리 뒤 보던 레이드로 돌아오기 위한 값.

@router.post("/admin/raids/categories/add")
async def add_category(
    name: str = Form(...), sort_order: int = Form(0), return_raid: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_add_category(user["discord_id"], name.strip(), sort_order)
    return _redirect(
        "카테고리를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, _raids_path(return_raid),
        "카테고리를 추가했습니다.",
    )


@router.post("/admin/raids/categories/delete")
async def delete_category(
    name: str = Form(...), return_raid: str = Form(""), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_delete_category(user["discord_id"], name)
    return _redirect("카테고리를 삭제하지 못했습니다.", result, _raids_path(return_raid), "카테고리를 삭제했습니다.")


@router.post("/admin/raids/categories/extreme")
async def set_category_extreme(
    name: str = Form(...), is_extreme: bool = Form(False), return_raid: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_category_extreme(user["discord_id"], name, is_extreme)
    return _redirect("변경하지 못했습니다.", result, _raids_path(return_raid))


@router.post("/admin/raids/categories/rename")
async def rename_category(
    old_name: str = Form(...), new_name: str = Form(...), return_raid: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_rename_category(user["discord_id"], old_name, new_name.strip())
    return _redirect("이름을 바꾸지 못했습니다.", result, _raids_path(return_raid), "카테고리 이름을 바꿨습니다.")


@router.post("/admin/raids/categories/order")
async def reorder_categories(
    order: str = Form(...), return_raid: str = Form(""), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_reorder_categories(user["discord_id"], _parse_order(order))
    return _redirect("순서를 저장하지 못했습니다.", result, _raids_path(return_raid), "순서를 저장했습니다.")


# 순서 — 레이드는 카테고리별 배열이다. 왼쪽 목록의 "순서 저장" 한 번이 바뀐 카테고리 전부를 보낸다.

@router.post("/admin/raids/order")
async def reorder_raids(
    category: str = Form(...), order: str = Form(...), return_raid: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_reorder_raids(user["discord_id"], category, _parse_order(order))
    return _redirect("순서를 저장하지 못했습니다.", result, _raids_path(return_raid), "순서를 저장했습니다.")


@router.post("/admin/raids/order-all")
async def reorder_raids_all(
    orders: str = Form(...), return_raid: str = Form(""), user: dict = Depends(require_admin),
):
    """orders: {"카테고리": ["레이드", ...], ...} JSON — 카테고리마다 기존 순서 저장을 부른다."""
    try:
        data = json.loads(orders)
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict) or not data:
        return redirect_with_toast(_raids_path(return_raid), "바뀐 순서가 없습니다.", "info")
    for category, order in data.items():
        if not isinstance(order, list):
            continue
        result = await bot_client.admin_reorder_raids(user["discord_id"], str(category), [str(x) for x in order])
        if not result.get("success"):
            return redirect_with_toast(
                _raids_path(return_raid), result.get("reason") or f"{category} 순서를 저장하지 못했습니다.", "error",
            )
    return redirect_with_toast(_raids_path(return_raid), "순서를 저장했습니다.")


# 난이도

@router.post("/admin/raids/difficulties/add")
async def add_difficulty(
    raid_name: str = Form(...), difficulty: str = Form(...),
    min_level: int = Form(...), total_slots: int = Form(...),
    party_split: str = Form(""), gates: int = Form(1), clear_gold: str = Form(""),
    user: dict = Depends(require_admin),
):
    split, split_error = _parse_split(party_split)
    gold, gold_error = _parse_gold(clear_gold)
    if split_error or gold_error:
        return redirect_with_toast(_raids_path(raid_name), split_error or gold_error, "error")
    result = await bot_admin.add_difficulty(
        user["discord_id"], raid_name, difficulty.strip(), min_level, total_slots, split, gates, gold,
    )
    return _redirect(
        "난이도를 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, _raids_path(raid_name),
        "난이도를 추가했습니다.",
    )


@router.post("/admin/raids/difficulties/update")
async def update_difficulty(
    raid_name: str = Form(...), difficulty: str = Form(...),
    min_level: int = Form(...), total_slots: int = Form(...),
    party_split: str = Form(""), gates: int = Form(1), clear_gold: str = Form(""),
    user: dict = Depends(require_admin),
):
    split, split_error = _parse_split(party_split)
    gold, gold_error = _parse_gold(clear_gold)
    if split_error or gold_error:
        return redirect_with_toast(_raids_path(raid_name), split_error or gold_error, "error")
    result = await bot_admin.update_difficulty(
        user["discord_id"], raid_name, difficulty, min_level, total_slots, split, gates, gold,
    )
    return _redirect("난이도를 수정하지 못했습니다.", result, _raids_path(raid_name), "난이도를 저장했습니다. 이미 개설된 공대에는 적용되지 않습니다.")


@router.post("/admin/raids/difficulties/save")
async def save_difficulty(
    raid_name: str = Form(...), old_difficulty: str = Form(...), difficulty: str = Form(...),
    min_level: int = Form(...), total_slots: int = Form(...),
    party_split: str = Form(""), gates: int = Form(1), clear_gold: str = Form(""),
    user: dict = Depends(require_admin),
):
    """난이도 수정 대화상자 — 이름이 바뀌었으면 연쇄 변경을 먼저 하고, 수치를 저장한다."""
    uid = user["discord_id"]
    split, split_error = _parse_split(party_split)
    gold, gold_error = _parse_gold(clear_gold)
    if split_error or gold_error:
        return redirect_with_toast(_raids_path(raid_name), split_error or gold_error, "error")
    difficulty = difficulty.strip()
    current = old_difficulty
    if difficulty and difficulty != old_difficulty:
        result = await bot_client.admin_rename_difficulty(uid, raid_name, old_difficulty, difficulty)
        if not result.get("success"):
            return redirect_with_toast(_raids_path(raid_name), result.get("reason") or "이름을 바꾸지 못했습니다.", "error")
        if not result.get("unchanged"):
            await notification_store.rename_difficulty(raid_name, old_difficulty, difficulty)
        current = difficulty
    result = await bot_admin.update_difficulty(uid, raid_name, current, min_level, total_slots, split, gates, gold)
    return _redirect("난이도를 수정하지 못했습니다.", result, _raids_path(raid_name), "난이도를 저장했습니다. 이미 개설된 공대에는 적용되지 않습니다.")


@router.post("/admin/raids/difficulties/rename")
async def rename_difficulty(
    raid_name: str = Form(...), old_difficulty: str = Form(...), new_difficulty: str = Form(...),
    user: dict = Depends(require_admin),
):
    new_difficulty = new_difficulty.strip()
    result = await bot_client.admin_rename_difficulty(user["discord_id"], raid_name, old_difficulty, new_difficulty)
    if result.get("success") and not result.get("unchanged"):
        await notification_store.rename_difficulty(raid_name, old_difficulty, new_difficulty)
    return _redirect("이름을 바꾸지 못했습니다.", result, _raids_path(raid_name))


@router.post("/admin/raids/difficulties/delete")
async def delete_difficulty(
    raid_name: str = Form(...), difficulty: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_delete_difficulty(user["discord_id"], raid_name, difficulty)
    return _redirect("난이도를 삭제하지 못했습니다.", result, _raids_path(raid_name), "난이도를 삭제했습니다.")


@router.post("/admin/raids/difficulties/order")
async def reorder_difficulties(
    raid_name: str = Form(...), order: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_reorder_difficulties(user["discord_id"], raid_name, _parse_order(order))
    return _redirect("순서를 저장하지 못했습니다.", result, _raids_path(raid_name), "순서를 저장했습니다.")


# ── 직업 ──────────────────────────────────────────────────

@router.get("/admin/classes")
async def admin_classes_page(
    request: Request, user: dict = Depends(require_admin),
):
    job_classes = await bot_client.get_job_classes()
    return await _render(request, "admin_classes.html", user, "admin_classes", {
        "job_classes": sorted(job_classes, key=lambda c: c["name"]),
    })


@router.post("/admin/classes/add")
async def add_class(
    name: str = Form(...), is_support: bool = Form(False), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_add_class(user["discord_id"], name.strip(), is_support)
    return _redirect("직업을 추가하지 못했습니다. (이미 있는 이름일 수 있어요)", result, "/admin/classes", "직업을 추가했습니다.")


@router.post("/admin/classes/delete")
async def delete_class(name: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_class(user["discord_id"], name)
    return _redirect("직업을 삭제하지 못했습니다.", result, "/admin/classes", "직업을 삭제했습니다.")


# ── 공대 ──────────────────────────────────────────────────
# 줄에서 바로 하는 건 열기 · 강제 마감/재개 · 클리어 되돌리기 · 스레드 잠금 해제.
# 강퇴·위임·일정 변경은 공대 상세의 "파티장 관리" 패널이 관리자에게도 열려 있어 거기로 보낸다.

_CLOSED_LABELS = {"disbanded": ("클리어", "ok"), "expired": ("기한 만료", "warn")}


def _closed_status_view(entry: dict) -> dict:
    label, tone = _CLOSED_LABELS.get(entry["status"], (entry["status"], ""))
    leader_slot = next((s for s in entry.get("slots") or [] if s["discord_id"] == entry["leader_id"]), None)
    return {**entry, "status_label": label, "status_tone": tone, "leader_character_name": leader_slot["character_name"] if leader_slot else None}


def _is_problem_party(party: dict, now: datetime) -> bool:
    """관리자 앱 Dashboard의 "문제" 규칙 — 메인의 "처리 안 한 내 공대"와 공용(webapp/format.py)."""
    return is_overdue_party(party, now)


def _leader_name(party: dict) -> str | None:
    slot = next((s for s in party.get("slots") or [] if s.get("discord_id") == party.get("leader_id")), None)
    return slot["character_name"] if slot else None


@router.get("/admin/parties")
async def admin_parties_page(
    request: Request, tab: str = "open", user: dict = Depends(require_admin),
):
    if tab not in ("open", "closed"):
        tab = "open"
    result, forum = await asyncio.gather(
        bot_client.admin_list_parties(config.DISCORD_GUILD_ID, user["discord_id"]),
        _safe(bot_client.admin_get_forum_channel(user["discord_id"], config.DISCORD_GUILD_ID), {}),
    )
    now = datetime.now(KST)
    open_parties = [
        {**party_view(p), "is_problem": _is_problem_party(p, now), "leader_name": _leader_name(p)}
        for p in result["open"]
    ]
    closed_parties = [_closed_status_view(p) for p in result["closed"]]
    open_parties.sort(key=lambda p: (p.get("scheduled_datetime") is None, p.get("scheduled_datetime") or ""))
    closed_parties.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    counts = {
        "recruiting": sum(1 for p in open_parties if p["status"] == "recruiting"),
        "full": sum(1 for p in open_parties if p["status"] == "full"),
        "closed": sum(1 for p in open_parties if p["status"] == "closed"),
        "problem": sum(1 for p in open_parties if p["is_problem"]),
    }
    return await _render(request, "admin_parties.html", user, "admin_parties", {
        "tab": tab,
        "open_parties": open_parties,
        "closed_parties": closed_parties,
        "counts": counts,
        "forum": forum or {},
    })


@router.post("/admin/forum-channel")
async def admin_set_forum_channel(
    channel_id: str = Form(...), user: dict = Depends(require_admin),
):
    """디스코드 /공대채널설정의 웹판 — 이게 없으면 웹 공대 개설이 "포럼 채널 미설정"으로 막혀
    관리자가 디스코드로 가야 했다."""
    result = await bot_client.admin_set_forum_channel(user["discord_id"], config.DISCORD_GUILD_ID, channel_id)
    return redirect_result("/admin/parties", result, "공대 모집 포럼 채널을 저장했습니다.", "저장하지 못했습니다.")


def _parties_back(tab: str) -> str:
    return "/admin/parties?tab=closed" if tab == "closed" else "/admin/parties"


@router.post("/admin/parties/{message_id}/close")
async def admin_force_close(message_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.close_party(message_id, user["discord_id"])
    return redirect_result("/admin/parties", result, "모집을 마감했습니다.", "마감하지 못했습니다.")


@router.post("/admin/parties/{message_id}/reopen")
async def admin_reopen(message_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.reopen_party(message_id, user["discord_id"])
    return redirect_result("/admin/parties", result, "모집을 다시 열었습니다.", "재개하지 못했습니다.")


@router.post("/admin/parties/{message_id}/revert-clear")
async def admin_list_revert_clear(message_id: str, user: dict = Depends(require_admin)):
    """목록의 ⋯ 메뉴에서 — 공대 상세의 같은 동작과 같은 처리(되살아난 공대 알림 억제 포함)."""
    party_events.note_admin_action(message_id, "revert")
    result = await bot_client.admin_revert_clear(message_id, user["discord_id"])
    if not result.get("success"):
        party_events.clear_admin_hint(message_id)
    return redirect_result("/admin/parties?tab=closed", result, "클리어를 되돌렸습니다.", "되돌리지 못했습니다.")


@router.post("/admin/parties/{message_id}/unlock")
async def admin_list_unlock(message_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.admin_unlock_party(message_id, user["discord_id"])
    return redirect_result("/admin/parties?tab=closed", result, "스레드 잠금을 해제했습니다.", "스레드 잠금을 해제하지 못했습니다.")


# ── 유저 ──────────────────────────────────────────────────
# 목록/검색은 화면에서 필터링한다(js-list-filter 대신 admin.js) — 등록 유저 수가 페이지네이션이 필요할 만큼 크지 않다.

STALE_DAYS = 14  # 관리자 앱의 "API 만료 의심" 기준과 동일


def _sync_age_days(last_sync: str | None, now_utc: datetime) -> int | None:
    """user_characters.cached_at(sqlite CURRENT_TIMESTAMP, UTC)과의 차이(일). 동기화
    기록이 아예 없으면 None."""
    if not last_sync:
        return None
    try:
        dt = datetime.fromisoformat(last_sync.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (now_utc - dt).days)


@router.get("/admin/users")
async def admin_users_page(
    request: Request, filter: str = "all", user: dict = Depends(require_admin),
):
    if filter not in ("all", "stale"):
        filter = "all"
    uid = user["discord_id"]
    users, parties = await asyncio.gather(
        bot_client.admin_list_users(uid, config.DISCORD_GUILD_ID),
        _safe(bot_client.admin_list_parties(config.DISCORD_GUILD_ID, uid), {"open": []}),
    )
    joined: dict[str, int] = {}
    leading: set[str] = set()
    for p in (parties or {}).get("open", []):
        for s in p.get("slots") or []:
            joined[s["discord_id"]] = joined.get(s["discord_id"], 0) + 1
        if p.get("leader_id"):
            leading.add(p["leader_id"])
    now_utc = datetime.now(timezone.utc)
    for u in users:
        age = _sync_age_days(u.get("last_sync"), now_utc)
        u["sync_age_days"] = age
        u["is_stale"] = age is None or age >= STALE_DAYS
        # 봇이 한 번에 집계해 준다(character_count / last_active_at — 봇 internal.py admin_list_users
        # 문서 참고). 필드가 없거나 null이면 "-"/동기화 시각으로 대신 보여준다.
        u["char_count"] = u.get("character_count")
        last = u.get("last_active_at") or u.get("last_sync")
        u["last_seen"] = time_ago(last)
        u["last_seen_title"] = kst_time(last)
        u["party_count"] = joined.get(u["discord_id"], 0)
        u["is_leader"] = u["discord_id"] in leading
        u["display_name"] = u.get("representative") or u.get("discord_nick") or u["discord_id"]
    stale_count = sum(1 for u in users if u["is_stale"])
    visible = [u for u in users if u["is_stale"]] if filter == "stale" else users
    return await _render(request, "admin_users.html", user, "admin_users", {
        "users": visible, "filter": filter, "total_count": len(users), "stale_count": stale_count,
        "stale_days": STALE_DAYS,
    })


@router.get("/admin/users/{target_discord_id}/details")
async def admin_user_details(
    request: Request, target_discord_id: str, user: dict = Depends(require_admin),
):
    """유저 행을 펼칠 때 캐릭터/참여 이력을 지연 조회 — 목록 조회 한 번에
    전체 유저의 캐릭터/이력까지 같이 가져오면 유저 수만큼 N+1이 생긴다."""
    characters, history = await asyncio.gather(
        bot_client.admin_get_user_characters(user["discord_id"], target_discord_id),
        bot_client.admin_get_user_history(user["discord_id"], target_discord_id),
    )
    entries = [_history_view(e) for e in history["entries"]]
    return templates.TemplateResponse(
        request, "_admin_user_details.html", {"characters": characters, "entries": entries},
    )


@router.get("/admin/users/{target_discord_id}/impact")
async def admin_user_impact(
    request: Request, target_discord_id: str, user: dict = Depends(require_admin),
):
    """내보내기 대화상자에 채울 영향 범위 조각 — 봇이 이 조회를 모르면(None) 안내 문구만 돌려준다."""
    impact = await bot_admin.user_impact(user["discord_id"], target_discord_id)
    return templates.TemplateResponse(request, "_admin_user_impact.html", {"impact": impact})


@router.post("/admin/users/{target_discord_id}/delete")
async def admin_delete_user_route(target_discord_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_user(user["discord_id"], target_discord_id)
    return _redirect("유저 데이터를 삭제하지 못했습니다.", result, "/admin/users", "유저를 내보냈습니다.")


# ── 통계 (관리자 앱 Stats.tsx의 클리어/활동 탭) ────────────────────────

STATS_TABS = [("clears", "클리어"), ("activity", "활동")]


@router.get("/admin/stats")
async def admin_stats_page(
    request: Request, tab: str = "clears", week_key: str | None = None,
    user: dict = Depends(require_admin),
):
    if tab not in dict(STATS_TABS):
        tab = "clears"
    uid = user["discord_id"]
    ctx: dict = {"tabs": STATS_TABS, "tab": tab}
    if tab == "clears":
        weeks = await bot_client.admin_stats_weeks(uid)
        week = week_key if week_key in weeks["weeks"] else weeks["current"]
        weekly, characters = await asyncio.gather(
            bot_client.admin_stats_weekly(uid, week),
            bot_client.admin_stats_characters(uid, week),
        )
        ctx.update(weeks=weeks["weeks"], week=week, weekly=weekly["data"], characters=characters["data"])
    else:
        activity = await bot_client.admin_stats_activity(uid, config.DISCORD_GUILD_ID)
        ctx.update(
            weekly_parties=activity["weekly_parties"],
            popular_raids=activity["popular_raids"],
            active_users=(activity.get("active_users") or {}).get("user_count", 0),
        )
    return await _render(request, "admin_stats.html", user, "admin_stats", ctx)


def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # BOM — 엑셀이 UTF-8 한글을 깨뜨리지 않게
    return Response(
        "﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/stats/export")
async def admin_stats_export(
    kind: str, week_key: str | None = None, user: dict = Depends(require_admin),
):
    uid = user["discord_id"]
    if kind == "weekly":
        data = await bot_client.admin_stats_weekly(uid, week_key)
        return _csv_response(
            f"clears-{data['week_key']}.csv", ["레이드", "난이도", "클리어 수"],
            [[r["raid_name"], r["difficulty"], r["count"]] for r in data["data"]],
        )
    if kind == "characters":
        data = await bot_client.admin_stats_characters(uid, week_key)
        return _csv_response(
            f"character-clears-{data['week_key']}.csv", ["디스코드 ID", "대표 캐릭터", "캐릭터", "클리어 수"],
            [[r["discord_id"], r.get("representative") or "", r["character_name"], r["clears"]] for r in data["data"]],
        )
    activity = await bot_client.admin_stats_activity(uid, config.DISCORD_GUILD_ID)
    if kind == "popular_raids":
        return _csv_response(
            "popular-raids.csv", ["레이드", "난이도", "공대 수"],
            [[r["raid_name"], r["difficulty"], r["count"]] for r in activity["popular_raids"]],
        )
    return _csv_response(
        "weekly-parties.csv", ["주차", "공대 수"],
        [[r["week"], r["count"]] for r in activity["weekly_parties"]],
    )


# ── 알림·구독 ─────────────────────────────────────────────

NOTIFICATION_TABS = [
    ("subscriptions", "구독 현황"), ("logs", "발송 로그"), ("broadcast", "전체 공지"), ("items", "시세 아이템"),
]


@router.get("/admin/notifications")
async def admin_notifications_page(
    request: Request, tab: str = "subscriptions", unresolved: str = "",
    user: dict = Depends(require_admin),
):
    if tab not in dict(NOTIFICATION_TABS):
        tab = "subscriptions"
    uid = user["discord_id"]
    ctx: dict = {"tabs": NOTIFICATION_TABS, "tab": tab}
    if tab == "subscriptions":
        subs = await bot_client.admin_subscriptions(uid)
        groups: dict[tuple, dict] = {}
        for s in subs:
            key = (s["raid_name"], s.get("difficulty") or "전체")
            group = groups.setdefault(key, {"raid_name": key[0], "difficulty": key[1], "subscribers": []})
            group["subscribers"].append({"discord_id": s["discord_id"], "name": s.get("representative") or s["discord_id"]})
        ctx.update(groups=list(groups.values()), total_subscriptions=len(subs))
    elif tab == "logs":
        ctx.update(logs=await bot_client.admin_notification_logs(uid, 200))
    elif tab == "broadcast":
        status = await bot_admin.broadcast_status(uid)
        ctx.update(
            broadcast=status if status.get("total") else {},
            broadcast_running=bool(status.get("total")) and not status.get("done"),
        )
    else:
        tracked = await bot_admin.get_tracked_items(uid)
        ctx.update(
            tracked_available=tracked is not None,
            tracked_names=(tracked or {}).get("names") or [],
            unresolved=[n for n in (unresolved.split(",") if unresolved else (tracked or {}).get("unresolved") or []) if n],
        )
    return await _render(request, "admin_notifications.html", user, "admin_notifications", ctx)


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.post("/admin/notifications/broadcast")
async def admin_broadcast(request: Request, content: str = Form(...), user: dict = Depends(require_admin)):
    """JSON을 받겠다고(Accept) 하면 {success, reason, queued, sent, total}을 그대로 돌려준다 — 화면은 이걸로
    진행률을 띄운다. 일반 폼 제출은 토스트와 함께 되돌아간다(발송은 봇이 뒤에서 계속)."""
    result = await bot_client.admin_notify_all(user["discord_id"], content.strip())
    if _wants_json(request):
        return JSONResponse({
            "success": bool(result.get("success")), "reason": result.get("reason"),
            "queued": bool(result.get("queued")), "sent": result.get("sent", 0), "total": result.get("total", 0),
        })
    if result.get("success"):
        if result.get("queued"):
            msg = f"{result.get('total', 0)}명에게 보내는 중입니다. 끝나면 작업 기록에 남습니다."
        else:
            msg = f"{result.get('total', 0)}명 중 {result.get('sent', 0)}명에게 DM을 보냈습니다. (DM을 막아둔 유저에게는 전달되지 않습니다)"
        return redirect_with_toast("/admin/notifications?tab=broadcast", msg)
    return _redirect("공지를 보내지 못했습니다.", result, "/admin/notifications?tab=broadcast")


@router.get("/admin/notifications/broadcast-status")
async def admin_broadcast_status(user: dict = Depends(require_admin)):
    status = await bot_admin.broadcast_status(user["discord_id"])
    return JSONResponse({
        "sent": status.get("sent", 0), "total": status.get("total", 0), "done": bool(status.get("done")),
        "active": bool(status.get("total")),
    })


@router.post("/admin/notifications/items")
async def admin_set_tracked_items(request: Request, user: dict = Depends(require_admin)):
    form = await request.form()
    seen: set[str] = set()
    names: list[str] = []
    for raw in form.getlist("names"):
        name = str(raw).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if len(names) > 8:
        return redirect_with_toast("/admin/notifications?tab=items", "시세로 볼 아이템은 최대 8개입니다.", "error")
    result = await bot_admin.set_tracked_items(user["discord_id"], names)
    if not result.get("success"):
        return redirect_with_toast("/admin/notifications?tab=items", result.get("reason") or "저장하지 못했습니다.", "error")
    missing = [n for n in result.get("unresolved") or [] if n]
    path = "/admin/notifications?tab=items"
    if missing:
        path += "&unresolved=" + quote(",".join(missing))
        return redirect_with_toast(path, f"저장했습니다. 시세에서 찾지 못한 아이템이 {len(missing)}개 있습니다.", "info")
    return redirect_with_toast(path, "저장했습니다.")


# ── 클리어 관리 (관리자 앱 Completions.tsx — 다른 유저의 과거 주차까지 편집) ────

async def _completion_grid(uid: str, target_discord_id: str, character_name: str, week: str) -> dict:
    raids, comp = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.admin_completions(uid, target_discord_id, character_name, week),
    )
    rows = [
        {"raid_name": name, "short_name": info.get("short_name") or name,
         "difficulties": list((info.get("difficulties") or {}).keys())}
        for name, info in raids.items()
    ]
    return {
        "rows": rows, "done": set(comp["completions"]),
        "target_discord_id": target_discord_id, "character_name": character_name, "week_key": week,
    }


@router.get("/admin/completions")
async def admin_completions_page(
    request: Request, target_discord_id: str | None = None, character_name: str | None = None,
    week_key: str | None = None, user: dict = Depends(require_admin),
):
    uid = user["discord_id"]
    users = await bot_client.admin_list_users(uid, config.DISCORD_GUILD_ID)
    ctx: dict = {
        "users": users,
        "target_discord_id": target_discord_id, "character_name": character_name,
        "characters": [], "weeks": [], "week": None, "grid": None,
    }
    if target_discord_id:
        characters, weeks = await asyncio.gather(
            bot_client.admin_get_user_characters(uid, target_discord_id),
            bot_client.admin_stats_weeks(uid),
        )
        week = week_key if week_key in weeks["weeks"] else weeks["current"]
        ctx.update(characters=characters, weeks=weeks["weeks"], week=week)
        if character_name and any(c["character_name"] == character_name for c in characters):
            ctx["grid"] = await _completion_grid(uid, target_discord_id, character_name, week)
        else:
            ctx["character_name"] = None
    return await _render(request, "admin_completions.html", user, "admin_completions", ctx)


@router.post("/admin/completions/toggle")
async def admin_completion_toggle(
    request: Request, target_discord_id: str = Form(...), character_name: str = Form(...),
    week_key: str = Form(...), raid_name: str = Form(...), difficulty: str = Form(...),
    done: str = Form(...), user: dict = Depends(require_admin),
):
    """htmx — 체크 하나를 바꾸고 그리드만 다시 그린다(레이드 체크 카드와 같은 패턴)."""
    uid = user["discord_id"]
    result = await bot_client.admin_set_completion(
        uid, target_discord_id, character_name, raid_name, difficulty, week_key, done == "1",
    )
    grid = await _completion_grid(uid, target_discord_id, character_name, week_key)
    if not result.get("success"):
        # 봇이 거부했는데(관리자 권한 상실 등) 성공 토스트를 띄우던 문제
        toast, toast_type = result.get("reason") or "체크를 저장하지 못했습니다.", "error"
    else:
        toast = f"{character_name} · {raid_name} {difficulty} {'완료 체크' if done == '1' else '체크 해제'}"
        toast_type = "success" if done == "1" else "info"
    return templates.TemplateResponse(
        request, "_admin_completion_grid.html", {"grid": grid},
        headers={"X-Toast": quote(toast), "X-Toast-Type": toast_type},
    )


# ── 작업 기록 ─────────────────────────────────────────────

ACTION_KINDS = [("all", "전체"), ("party", "공대"), ("raid", "레이드"), ("user", "유저")]
_SOURCE_LABELS = {"web": "웹", "discord": "디스코드", "api": "관리 API"}


def _when_label(iso: str | None) -> str:
    """작업 시각 — 한 시간 안은 'N분 전', 하루 안은 'N시간 전', 그 밖은 'MM/DD HH:MM'(한국 시간)."""
    rel = time_ago(iso)
    if rel and (rel.endswith("분 전") or rel.endswith("시간 전") or rel == "방금 전"):
        return rel
    return kst_time(iso, "%m/%d %H:%M") or rel or "-"


@router.get("/admin/actions")
async def admin_actions_page(request: Request, kind: str = "all", user: dict = Depends(require_admin)):
    if kind not in dict(ACTION_KINDS):
        kind = "all"
    data = await bot_admin.list_actions(user["discord_id"], kind, 100)
    items = []
    for a in (data or {}).get("items") or []:
        undone = a.get("undone_at")
        items.append({
            **a,
            "when": _when_label(a.get("at")),
            "when_title": kst_time(a.get("at"), "%Y-%m-%d %H:%M:%S"),
            "source_label": _SOURCE_LABELS.get(a.get("source"), a.get("source") or "-"),
            "can_undo": bool(a.get("undoable")) and not undone,
            "undone_when": _when_label(undone) if undone else None,
        })
    return await _render(request, "admin_actions.html", user, "admin_actions", {
        "kinds": ACTION_KINDS, "kind": kind, "items": items, "available": data is not None,
    })


@router.post("/admin/actions/{action_id}/undo")
async def admin_undo_action(action_id: str, kind: str = Form("all"), user: dict = Depends(require_admin)):
    result = await bot_admin.undo_action(user["discord_id"], action_id)
    path = "/admin/actions" if kind not in dict(ACTION_KINDS) or kind == "all" else f"/admin/actions?kind={kind}"
    return redirect_result(path, result, "되돌렸습니다.", "되돌리지 못했습니다.")
