"""홈(/main) — 이번 주 숙제표 + 할 일 + 일정 + 로스트아크 공용 정보.

왼쪽은 숙제표(캐릭터 × 레이드 한 표)와 이번 주 골드, 오른쪽은 지금 처리할 것(초대·일정 지난 공대) →
내 일정 → 오늘의 콘텐츠 → 시세 → 이벤트 → 들어갈 만한 공대 순.
숙제표는 봇의 /raid-check-summary 한 번으로 그린다. 로아 API 카드(오늘의 콘텐츠·시세·이벤트·점검)는
봇 쪽 엔드포인트가 없거나 느려도 홈이 깨지지 않도록 비워 둔다.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client, bot_home
from webapp.format import KST, _parse, is_overdue_party, party_view, period_view, reset_view
from webapp.raid_check import eligible_characters, extreme_raids
from webapp.routes.invites import _build_invite_views
from webapp.templating import templates

router = APIRouter()

MY_SCHEDULE_LIMIT = 5
OPPORTUNITY_LIMIT = 3
EVENT_LIMIT = 3
HOMEWORK_FILTER_FROM = 6   # 캐릭터가 이보다 많으면 "숙제 남은 캐릭터만" 필터를 기본으로 켠다
SCROLL_FROM_COLUMNS = 5    # 레이드 열이 이보다 많으면 표 안에서만 가로 스크롤
_SEG_BTN = 58              # 난이도 버튼 폭(px) — home.css와 같은 값


def split_parties(parties: list[dict], discord_id: str, max_level: float) -> tuple[list, list]:
    """내가 이미 속한 공대(임박순)와, 아직 안 들어갔지만 입장 가능한 공대를 나눈다."""
    mine, opportunities = [], []
    for p in parties:
        joined = p.get("leader_id") == discord_id or any(
            s["discord_id"] == discord_id for s in p.get("slots") or []
        )
        view = party_view(p)
        if joined:
            if not view["schedule"]["is_past"]:
                mine.append(view)
        elif (
            p["status"] == "recruiting"
            and (p.get("min_level") or 0) <= max_level
            and not view["schedule"]["is_past"]
        ):
            opportunities.append(view)

    key = lambda p: p.get("scheduled_datetime") or "9999"
    mine.sort(key=key)
    opportunities.sort(key=key)
    return mine, opportunities


async def _safe(coro, default):
    """카드 하나의 봇 호출이 실패해도 홈 전체가 502로 떨어지지 않게 — 그 카드만 비운다."""
    try:
        return await coro
    except Exception:
        return default


# ── 숙제표 ──────────────────────────────────────────────

def _seg_width(n_diffs: int) -> int:
    return max(120, n_diffs * _SEG_BTN + 4)


def build_homework(summary: dict) -> dict:
    """/raid-check-summary → 숙제표 표시 모델.

    columns — 모든 캐릭터에서 한 번이라도 보이는 레이드(봇 순서). 칸 폭은 그 열의 최대 난이도 개수로 정한다.
    rows    — 입장 가능한 레이드가 하나도 없는 캐릭터는 뺀다(누를 게 없다). cells는 columns와 같은 길이이고
              그 캐릭터에게 해당 없는 레이드는 None.
    """
    characters = summary.get("characters") or []
    columns: list[dict] = []
    index: dict[str, int] = {}
    for c in characters:
        visible = set(c.get("visible_raid_names") or [])
        for r in c.get("applicable_raids") or []:
            name = r.get("raid_name")
            if name not in visible:
                continue
            if name not in index:
                index[name] = len(columns)
                columns.append({"raid_name": name, "short_name": r.get("short_name") or name, "max_diffs": 0})
            col = columns[index[name]]
            col["max_diffs"] = max(col["max_diffs"], len(r.get("difficulties") or []))
    for col in columns:
        col["width"] = _seg_width(col["max_diffs"])

    rows = []
    for c in characters:
        visible = set(c.get("visible_raid_names") or [])
        applicable = {r["raid_name"]: r for r in c.get("applicable_raids") or [] if r.get("raid_name") in visible}
        if not applicable:
            continue
        done = set(c.get("completions") or [])
        cells = []
        for col in columns:
            r = applicable.get(col["raid_name"])
            if r is None:
                cells.append(None)
                continue
            gold = r.get("difficulty_gold") or {}
            cells.append({
                "raid_name": r["raid_name"],
                "short_name": col["short_name"],
                "diffs": [
                    {"name": d, "on": f"{r['raid_name']}_{d}" in done, "gold": gold.get(d)}
                    for d in r.get("difficulties") or []
                ],
            })
        total = c.get("total_slots")
        total = len(applicable) if total is None else total
        done_count = c.get("done_count") or 0
        rows.append({
            "name": c["character_name"],
            "cls": c.get("character_class") or "",
            "item_level": c.get("item_level"),
            "cells": cells,
            "done": done_count,
            "total": total,
            "remaining": max(total - done_count, 0),
        })

    done_sum = sum(r["done"] for r in rows)
    total_sum = sum(r["total"] for r in rows)
    return {
        "columns": columns,
        "rows": rows,
        "done": done_sum,
        "total": total_sum,
        "pct": round(done_sum / total_sum * 100) if total_sum else 0,
        "filter_default": len(rows) > HOMEWORK_FILTER_FROM,
        "scroll": len(columns) > SCROLL_FROM_COLUMNS,
        "grid_cols": " ".join(f"{col['width']}px" for col in columns),
        "select_characters": [
            {"name": c["character_name"], "cls": c.get("character_class") or "", "item_level": c.get("item_level")}
            for c in characters
        ],
    }


def build_extreme(summary: dict) -> list[dict]:
    """원정대 단위 익스트림 행. 난이도마다 입장 가능한 캐릭터를 미리 구한다(1명이면 바로 체크, 여럿이면 고르는 메뉴)."""
    characters = summary.get("characters") or []
    raids = summary.get("raids") or {}
    live = {r["raid_name"]: r for r in extreme_raids(raids)} if raids else {}
    out = []
    for st in summary.get("extreme") or []:
        info = live.get(st.get("raid_name")) or {}
        difficulties = st.get("difficulties") or dict(info.get("difficulties") or {})
        until = st.get("available_until") or info.get("available_until")
        diffs = []
        for name, d in difficulties.items():
            eligible = eligible_characters(characters, (d or {}).get("min_level") or 0)
            diffs.append({
                "name": name,
                "on": bool(st.get("cleared")) and st.get("difficulty") == name,
                "eligible": [{"name": c["character_name"], "item_level": c.get("item_level")} for c in eligible],
            })
        out.append({
            "raid_name": st["raid_name"],
            "short_name": st.get("short_name") or st["raid_name"],
            "period": period_view(until) if until else None,
            "cleared": bool(st.get("cleared")),
            "character_name": st.get("character_name"),
            "difficulty": st.get("difficulty"),
            "diffs": diffs,
        })
    return out


def build_gold(summary: dict) -> dict | None:
    """이번 주 골드 — 관리자가 클리어 골드를 하나도 안 넣었으면 None(카드를 그리지 않는다)."""
    gold = summary.get("gold") or {}
    earned = gold.get("earned") or 0
    total = gold.get("total") or 0
    characters = summary.get("characters") or []
    rows = [
        {
            "name": c["character_name"],
            "earned": c.get("gold_earned") or 0,
            "remaining": max((c.get("gold_total") or 0) - (c.get("gold_earned") or 0), 0),
        }
        for c in characters
        if (c.get("gold_total") or 0) or (c.get("gold_earned") or 0)
    ]
    if not (earned or total):
        return None
    remaining_raids = sum(max((c.get("total_slots") or 0) - (c.get("done_count") or 0), 0) for c in characters)
    return {
        "earned": earned,
        "total": total,
        "pct": round(earned / total * 100) if total else 0,
        "rows": rows,
        "remaining_raids": remaining_raids,
    }


# ── 할 일·일정 ───────────────────────────────────────────

def leader_overview(party: dict, discord_id: str) -> dict | None:
    """내가 파티장인 공대의 채워야 할 자리/서포터 유무/일정 지남 여부. 파티장이 아니면 None."""
    if party.get("leader_id") != discord_id:
        return None
    slots = party.get("slots") or []
    total = party.get("total_slots") or 0
    return {
        "open_slots": max(total - len(slots), 0),
        "has_support": any(s.get("role") == "support" for s in slots),
        "overdue": is_overdue_party(party),
    }


def _schedule_item(href: str, title: str, meta: str, key: str | None, sch: dict) -> dict:
    day, _, time = sch["when"].rpartition(" ")
    return {
        "key": key or "9999", "href": href, "title": title, "meta": meta,
        "when_day": day, "when_time": time, "countdown": sch["countdown"], "tone": sch["tone"],
    }


def build_schedule(mine: list[dict], invites: list[dict], discord_id: str) -> list[dict]:
    """내 일정 — 참여 중인 공대와 응답 대기 중인 초대를 시간순으로 한 줄씩."""
    items = [
        _schedule_item(
            f"/parties/{p['message_id']}", f"{p['raid_name']} {p['difficulty']}",
            ("파티장" if p.get("leader_id") == discord_id else "참여") + f" · {p['filled']}/{p['total_slots']}명",
            p.get("scheduled_datetime"), p["schedule"],
        )
        for p in mine
    ]
    items += [
        _schedule_item(
            f"/parties/{inv['message_id']}", f"{inv['raid_name']} {inv['difficulty']}", "초대 대기 중",
            inv.get("scheduled_datetime"), inv["schedule"],
        )
        for inv in invites
        if not inv["schedule"].get("is_past")
    ]
    items.sort(key=lambda i: i["key"])
    return items


# ── 로스트아크 공용 데이터 ─────────────────────────────────

def _hm(value: str | None) -> str:
    dt = _parse(value)
    return dt.strftime("%H:%M") if dt else ""


def _until(target: datetime, now: datetime) -> str:
    """'2시간 14분 뒤' — 홈 카드용(공대 카운트다운보다 한 단계 자세히)."""
    minutes = int((target - now).total_seconds() // 60)
    if minutes < 1:
        return "곧 시작"
    if minutes < 60:
        return f"{minutes}분 뒤"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}시간 {mins}분 뒤" if mins else f"{hours}시간 뒤"
    return f"{hours // 24}일 뒤"


def _safe_url(value) -> str | None:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def build_maintenance(overview: dict) -> dict | None:
    """점검 배너 — 진행 중(active)이면 경고, 오늘·곧 있을 점검 공지면 안내로 보여준다.
    임시 점검 공지는 제목에 시각이 없는 경우가 많아(예: "11월 19일(목) 로스트아크 임시 점검 안내")
    봇이 active=False로 넘기는데, 예전엔 그걸 버려서 점검 당일에도 안내가 안 떴다."""
    m = overview.get("maintenance")
    if not isinstance(m, dict) or not m.get("title"):
        return None
    start, end = _hm(m.get("starts_at")), _hm(m.get("ends_at"))
    return {
        "active": bool(m.get("active")),
        "title": m.get("title") or "점검 중",
        "period": f"{start} ~ {end}" if start and end else "",
        "link": _safe_url(m.get("link")),
    }


# 오늘의 콘텐츠 탭 순서 — 로아 API 순서(섬 → 카오스게이트 → 모험 섬 …)를 따르면 정작 많이 보는 모험섬이
# 세 번째로 밀리고 일반 "섬"이 기본 탭이 됐다. 여기 없는 종류는 "섬" 바로 앞에 API 순서대로 둔다.
TODAY_TAB_ORDER = ["모험섬", "필드보스", "카오스게이트", "태초의섬", "로웬", "항해"]
TODAY_TAB_LAST = "섬"
TODAY_VISIBLE_ROWS = 6  # 탭마다 처음 보이는 줄 수 — 나머지는 "나머지 N개"로 접는다(카오스게이트는 13줄)


def _today_tab_key(label: str, api_index: int) -> tuple:
    if label in TODAY_TAB_ORDER:
        return (0, TODAY_TAB_ORDER.index(label))
    if label == TODAY_TAB_LAST:
        return (2, 0)
    return (1, api_index)


def build_today(overview: dict, now: datetime | None = None) -> dict | None:
    """오늘의 콘텐츠 — 카테고리별로 묶고, 항목마다 다음 시작 시각(없으면 마지막)과 남은 시간을 붙인다.
    탭은 TODAY_TAB_ORDER 순서, 줄은 곧 시작하는 순서로 정렬하고 오늘 일정이 끝난 항목은 아래로 보내 흐리게 한다."""
    now = now or datetime.now(KST)
    items = overview.get("today") or []
    if not isinstance(items, list):
        return None
    tabs: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        label = (it.get("category") or "기타").replace(" ", "")
        tab = next((t for t in tabs if t["label"] == label), None)
        if tab is None:
            tab = {"label": label, "rows": []}
            tabs.append(tab)
        times = sorted(t for t in (_parse(x) for x in it.get("times") or []) if t)
        upcoming = next((t for t in times if t >= now), None)
        shown = upcoming or (times[-1] if times else None)
        rewards = [r.get("name") for r in it.get("rewards") or [] if isinstance(r, dict) and r.get("name")]
        tab["rows"].append({
            "name": it.get("name") or "",
            "icon": _safe_url(it.get("icon")),
            "is_gold": bool(it.get("is_gold")),
            "rewards": " · ".join(rewards[:3]),
            "time": shown.strftime("%H:%M") if shown else "",
            "rel": _until(upcoming, now) if upcoming else ("종료" if shown else ""),
            "past": upcoming is None,
            "_sort": (upcoming is None, upcoming or shown or now),
        })
    if not tabs:
        return None
    tabs = [t for _, t in sorted(enumerate(tabs), key=lambda p: _today_tab_key(p[1]["label"], p[0]))]
    for t in tabs:
        t["rows"].sort(key=lambda r: r.pop("_sort"))
        t["more"] = t["rows"][TODAY_VISIBLE_ROWS:]
        t["rows"] = t["rows"][:TODAY_VISIBLE_ROWS]
    return {"date": f"{now.month}/{now.day} ({'월화수목금토일'[now.weekday()]})", "tabs": tabs}


def build_events(overview: dict, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(KST)
    rows = []
    for ev in overview.get("events") or []:
        if not isinstance(ev, dict):
            continue
        end = _parse(ev.get("end"))
        if end and end < now:
            continue
        days = (end.date() - now.date()).days if end else None
        rows.append({
            "title": ev.get("title") or "",
            "link": _safe_url(ev.get("link")),
            "dday": ("오늘" if days == 0 else f"D-{days}") if days is not None else "",
            "until": f"{end.month}/{end.day} {end.strftime('%H:%M')}까지" if end else "",
            "soon": days is not None and days <= 3,
            "key": end or datetime.max.replace(tzinfo=KST),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: r["key"])
    return {"count": len(rows), "rows": rows[:EVENT_LIMIT]}


def _spark(history: list) -> dict | None:
    values = [h.get("avg") for h in history if isinstance(h, dict) and isinstance(h.get("avg"), (int, float))][-7:]
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    w, h, pad = 92, 28, 3
    pts = []
    for i, v in enumerate(values):
        x = 2 + i * (w - 4) / (len(values) - 1)
        y = h / 2 if hi == lo else (h - pad) - (v - lo) / (hi - lo) * (h - 2 * pad)
        pts.append((round(x, 1), round(y, 1)))
    return {"points": " ".join(f"{x},{y}" for x, y in pts), "last": pts[-1]}


def build_prices(prices: dict) -> list[dict] | None:
    rows = []
    for it in prices.get("items") or []:
        if not isinstance(it, dict):
            continue
        pct = it.get("change_pct")
        pct = pct if isinstance(pct, (int, float)) else None
        rows.append({
            "name": it.get("name") or "",
            "pct": f"{pct:+.1f}%" if pct is not None else "—",
            "dir": None if not pct else ("up" if pct > 0 else "down"),
            "spark": _spark(it.get("history") or []),
        })
    return rows or None


# ── 컨텍스트 ─────────────────────────────────────────────

async def _dashboard_context(discord_id: str) -> dict:
    summary, all_parties, invites, overview, prices = await asyncio.gather(
        _safe(bot_home.get_raid_check_summary(discord_id), None),
        _safe(bot_client.list_parties(config.DISCORD_GUILD_ID), None),
        _safe(_build_invite_views(discord_id), []),
        bot_home.get_loa_overview(discord_id),
        bot_home.get_loa_prices(),
    )
    summary_failed = summary is None
    summary = summary or {}
    parties = all_parties or []

    characters = summary.get("characters") or []
    max_level = max((c.get("item_level") or 0) for c in characters) if characters else 0
    mine, opportunities = split_parties(parties, discord_id, max_level)
    overdue_mine = [
        {**party_view(p), "leader": leader_overview(p, discord_id)}
        for p in parties
        if p.get("leader_id") == discord_id and is_overdue_party(p)
    ]

    overview_ok = bool(overview.get("available"))
    return {
        "summary_failed": summary_failed,
        "has_characters": bool(characters),
        "homework": build_homework(summary),
        "extreme": build_extreme(summary),
        "gold": build_gold(summary),
        "reset": reset_view(),
        "invites": invites,
        "overdue_parties": overdue_mine,
        "todo_count": len(invites) + len(overdue_mine),
        "schedule": build_schedule(mine, invites, discord_id)[:MY_SCHEDULE_LIMIT],
        "opportunities": opportunities[:OPPORTUNITY_LIMIT],
        "opportunity_count": len(opportunities),
        "maintenance": build_maintenance(overview),
        "today": build_today(overview) if overview_ok else None,
        "events": build_events(overview) if overview_ok else None,
        "gold_island_subscribed": bool(overview.get("gold_island_subscribed")),
        "loa_note": None if overview_ok else (overview.get("reason") or None),
        "prices": build_prices(prices) if prices.get("available") else None,
    }


@router.get("/main")
async def main_dashboard(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _dashboard_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "main.html", {"user": user, "active": "main", **ctx}
    )


@router.get("/main/gold")
async def main_gold_fragment(request: Request, user: dict = Depends(get_current_user)):
    """체크할 때마다 이번 주 골드 카드만 새로 그려 가져간다(home.js)."""
    summary = await _safe(bot_home.get_raid_check_summary(user["discord_id"]), {})
    return templates.TemplateResponse(request, "_home_gold.html", {"gold": build_gold(summary)})


@router.get("/nav-badges")
async def nav_badges(user: dict = Depends(get_current_user)):
    """사이드바 숫자. 홈 = 할 일(받은 초대 + 일정 지난 내 공대), 공대 = 모집 중.
    페이지 렌더를 막지 않도록 로드 후 따로 가져간다."""
    parties, invites = await asyncio.gather(
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_my_invites(user["discord_id"]),
    )
    overdue = sum(1 for p in parties if p.get("leader_id") == user["discord_id"] and is_overdue_party(p))
    return {
        "parties": sum(1 for p in parties if p["status"] == "recruiting"),
        "invites": len(invites),
        "home": len(invites) + overdue,
    }
