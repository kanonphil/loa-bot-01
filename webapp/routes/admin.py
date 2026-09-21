"""관리자 탭 — 1단계: 카테고리/레이드/난이도/직업 CRUD.

카테고리/레이드/난이도는 서로 계층 관계(카테고리 → 레이드 → 난이도)라 한 페이지
안의 탭(쿼리 파라미터 기반, party_list.html/ranking.html과 같은 패턴)으로 묶여있다.
직업은 그 계층과 무관한 별개 데이터(딜러/서포터 분류만 씀)라 /admin/classes로
완전히 분리한다 — 사용자가 "레이드 관리에 왜 직업이 껴있냐"고 명시적으로 지적했다.

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
from starlette.responses import RedirectResponse, Response

from webapp import config
from webapp.auth.dependencies import require_admin
from webapp.clients import bot_client
from webapp.format import party_view
from webapp.routes.party import _history_view
from webapp.templating import templates

router = APIRouter()

TABS = [
    ("categories", "카테고리"),
    ("raids", "레이드"),
    ("difficulties", "난이도"),
]
_TAB_KEYS = {key for key, _ in TABS}


KST = timezone(timedelta(hours=9))


def _parse_order(raw: str) -> list[str]:
    """순서 저장 폼의 hidden input — 드래그/▲▼로 만든 최종 배열을 JSON으로 받는다."""
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


def _redirect(fallback_reason: str, result: dict, path: str) -> RedirectResponse:
    if not result.get("success"):
        reason = quote(result.get("reason") or fallback_reason)
        sep = "&" if "?" in path else "?"
        return RedirectResponse(f"{path}{sep}error={reason}", status_code=303)
    return RedirectResponse(path, status_code=303)


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


# ── 레이드 관리: 순서 변경 / 카테고리 이동 / 운영 기간 (관리자 앱에만 있던 기능) ──

@router.post("/admin/raids/categories/order")
async def reorder_categories(order: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_reorder_categories(user["discord_id"], _parse_order(order))
    return _redirect("순서를 저장하지 못했습니다.", result, "/admin/raids?tab=categories")


@router.post("/admin/raids/order")
async def reorder_raids(
    category: str = Form(...), order: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_reorder_raids(user["discord_id"], category, _parse_order(order))
    return _redirect("순서를 저장하지 못했습니다.", result, "/admin/raids?tab=raids")


@router.post("/admin/raids/difficulties/order")
async def reorder_difficulties(
    raid_name: str = Form(...), order: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_reorder_difficulties(user["discord_id"], raid_name, _parse_order(order))
    return _redirect(
        "순서를 저장하지 못했습니다.", result, f"/admin/raids?tab=difficulties&raid={quote(raid_name)}",
    )


@router.post("/admin/raids/move-category")
async def move_raid_category(
    name: str = Form(...), category: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_move_raid_category(user["discord_id"], name, category)
    return _redirect("카테고리를 옮기지 못했습니다.", result, "/admin/raids?tab=raids")


@router.post("/admin/raids/period")
async def set_raid_period(
    name: str = Form(...), available_from: str = Form(""), available_until: str = Form(""),
    user: dict = Depends(require_admin),
):
    result = await bot_client.admin_set_raid_period(
        user["discord_id"], name, _period_to_iso(available_from), _period_to_iso(available_until),
    )
    return _redirect("운영 기간을 저장하지 못했습니다.", result, "/admin/raids?tab=raids")


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
    result, bot_status = await asyncio.gather(
        bot_client.admin_list_parties(config.DISCORD_GUILD_ID, user["discord_id"]),
        bot_client.admin_status(user["discord_id"]),
    )
    now = datetime.now(KST)
    open_parties = [{**party_view(p), "is_problem": _is_problem_party(p, now)} for p in result["open"]]
    closed_parties = [_closed_status_view(p) for p in result["closed"]]
    open_parties.sort(key=lambda p: (p.get("scheduled_datetime") is None, p.get("scheduled_datetime") or ""))
    closed_parties.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    counts = {
        "recruiting": sum(1 for p in open_parties if p["status"] == "recruiting"),
        "full": sum(1 for p in open_parties if p["status"] == "full"),
        "closed": sum(1 for p in open_parties if p["status"] == "closed"),
        "problem": sum(1 for p in open_parties if p["is_problem"]),
    }

    return templates.TemplateResponse(
        request,
        "admin_parties.html",
        {
            "user": user,
            "active": "admin_parties",
            "tab": tab,
            "open_parties": open_parties,
            "closed_parties": closed_parties,
            "counts": counts,
            "bot_status": bot_status,
        },
    )


def _is_problem_party(party: dict, now: datetime) -> bool:
    """일정이 이미 지났는데 아직 모집중/파티완성인 공대 — 관리자 앱 Dashboard의
    "문제" 규칙 그대로. 파티장이 클리어/취소를 안 눌러 방치된 공대를 찾아낸다."""
    sdt = party.get("scheduled_datetime")
    if not sdt or party.get("status") not in ("recruiting", "full"):
        return False
    try:
        dt = datetime.fromisoformat(sdt)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt < now


# ── 유저 관리 (Electron 관리자 앱에만 있던 기능을 웹에도 추가) ────────
# 목록/검색은 기존 종료된 공대 목록과 같은 방식으로 클라이언트에서 필터링한다
# (js-list-filter) — 등록 유저 수가 페이지네이션이 필요할 만큼 크지 않다.

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
    users = await bot_client.admin_list_users(user["discord_id"], config.DISCORD_GUILD_ID)
    now_utc = datetime.now(timezone.utc)
    for u in users:
        age = _sync_age_days(u.get("last_sync"), now_utc)
        u["sync_age_days"] = age
        u["is_stale"] = age is None or age >= STALE_DAYS
    stale_count = sum(1 for u in users if u["is_stale"])
    visible = [u for u in users if u["is_stale"]] if filter == "stale" else users
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "user": user, "active": "admin_users", "users": visible,
            "filter": filter, "total_count": len(users), "stale_count": stale_count,
            "stale_days": STALE_DAYS,
        },
    )


@router.get("/admin/users/{target_discord_id}/details")
async def admin_user_details(
    request: Request, target_discord_id: str, user: dict = Depends(require_admin),
):
    """유저 행을 펼칠 때 캐릭터/참여 이력을 지연 조회(htmx) — 목록 조회 한 번에
    전체 유저의 캐릭터/이력까지 같이 가져오면 유저 수만큼 N+1이 생긴다."""
    characters, history = await asyncio.gather(
        bot_client.admin_get_user_characters(user["discord_id"], target_discord_id),
        bot_client.admin_get_user_history(user["discord_id"], target_discord_id),
    )
    entries = [_history_view(e) for e in history["entries"]]
    return templates.TemplateResponse(
        request, "_admin_user_details.html", {"characters": characters, "entries": entries},
    )


@router.post("/admin/users/{target_discord_id}/delete")
async def admin_delete_user_route(target_discord_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.admin_delete_user(user["discord_id"], target_discord_id)
    return _redirect("유저 데이터를 삭제하지 못했습니다.", result, "/admin/users")


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
    ctx: dict = {"user": user, "active": "admin_stats", "tabs": STATS_TABS, "tab": tab}
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
    return templates.TemplateResponse(request, "admin_stats.html", ctx)


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


# ── 알림·구독 (관리자 앱 Subscriptions.tsx + 전체 공지) ───────────────────

NOTIFICATION_TABS = [("subscriptions", "구독 현황"), ("logs", "발송 로그"), ("broadcast", "전체 공지")]


@router.get("/admin/notifications")
async def admin_notifications_page(
    request: Request, tab: str = "subscriptions", error: str | None = None,
    sent: int | None = None, total: int | None = None,
    user: dict = Depends(require_admin),
):
    if tab not in dict(NOTIFICATION_TABS):
        tab = "subscriptions"
    uid = user["discord_id"]
    ctx: dict = {
        "user": user, "active": "admin_notifications", "tabs": NOTIFICATION_TABS, "tab": tab,
        "error": error, "sent": sent, "total": total,
    }
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
    else:
        status = await bot_client.admin_status(uid)
        ctx.update(user_count=status.get("user_count", 0))
    return templates.TemplateResponse(request, "admin_notifications.html", ctx)


@router.post("/admin/notifications/broadcast")
async def admin_broadcast(content: str = Form(...), user: dict = Depends(require_admin)):
    result = await bot_client.admin_notify_all(user["discord_id"], content.strip())
    if result.get("success"):
        return RedirectResponse(
            f"/admin/notifications?tab=broadcast&sent={result.get('sent', 0)}&total={result.get('total', 0)}",
            status_code=303,
        )
    return _redirect("공지를 보내지 못했습니다.", result, "/admin/notifications?tab=broadcast")


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
        "user": user, "active": "admin_completions", "users": users,
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
    return templates.TemplateResponse(request, "admin_completions.html", ctx)


@router.post("/admin/completions/toggle")
async def admin_completion_toggle(
    request: Request, target_discord_id: str = Form(...), character_name: str = Form(...),
    week_key: str = Form(...), raid_name: str = Form(...), difficulty: str = Form(...),
    done: str = Form(...), user: dict = Depends(require_admin),
):
    """htmx — 체크 하나를 바꾸고 그리드만 다시 그린다(레이드 체크 카드와 같은 패턴)."""
    uid = user["discord_id"]
    await bot_client.admin_set_completion(
        uid, target_discord_id, character_name, raid_name, difficulty, week_key, done == "1",
    )
    grid = await _completion_grid(uid, target_discord_id, character_name, week_key)
    return templates.TemplateResponse(request, "_admin_completion_grid.html", {"grid": grid})
