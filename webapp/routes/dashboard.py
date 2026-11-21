"""홈(/main) — 이번 주 숙제 + 할 일 + 공대 + 로스트아크 공용 정보.

위에 숫자 카드 4장(숙제·내 일정·참여 가능 공대·초기화까지), 그 아래
왼쪽 큰 칸 = 할 일 → 숙제 → 공대, 오른쪽 작은 칸 = 오늘의 콘텐츠 → 진행 중 이벤트 → 시세 → 이번 주 골드.
숙제는 캐릭터마다 그 캐릭터가 고른 레이드만 칸으로 보여준다(다른 캐릭터의 레이드 열이 끼어들지 않는다).
숙제는 봇의 /raid-check-summary 한 번으로 그린다. 로아 API 카드(오늘의 콘텐츠·시세·이벤트·점검)는
봇 쪽 엔드포인트가 없거나 느려도 홈이 깨지지 않도록 비워 둔다.
"""
import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from webapp import config, party_logic
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client, bot_home
from webapp.format import KST, _parse, is_overdue_party, next_reset, party_view, period_view
from webapp.raid_check import eligible_characters, extreme_raids
from webapp.routes.invites import _build_invite_views
from webapp.templating import templates

router = APIRouter()

PARTY_ROWS = 5             # 공대 카드 탭마다 보여줄 줄 수
EVENT_LIMIT = 3
TILES_PER_ROW = 3          # 숙제 칸은 한 줄에 3개 — 고른 레이드가 그보다 적으면 "+ 레이드 고르기" 빈 칸


def split_parties(parties: list[dict], discord_id: str) -> list[dict]:
    """내가 이미 속한(파티장이거나 자리에 있는) 공대 중 일정이 안 지난 것, 임박순."""
    mine = []
    for p in parties:
        joined = p.get("leader_id") == discord_id or any(
            s["discord_id"] == discord_id for s in p.get("slots") or []
        )
        view = party_view(p)
        if joined and not view["schedule"]["is_past"]:
            mine.append(view)
    mine.sort(key=lambda p: p.get("scheduled_datetime") or "9999")
    return mine


def joinable_parties(
    parties: list[dict], summary: dict | None, discord_id: str, now: datetime | None = None,
) -> list[dict]:
    """모집 중이고 일정이 안 지났으며 내 캐릭터 하나라도 참여 가능한 공대(공대 목록의 "참여 가능"과 같은 판정).
    줄마다 party_view + join(참여 칸 상태, 캐릭터 후보) + comp(딜/폿 현황) + fits(참여 가능한 캐릭터 이름)."""
    if not summary:
        return []
    raids = summary.get("raids") or {}
    out = []
    for p in parties:
        if p.get("status") != "recruiting":
            continue
        view = party_view(p)
        if view["schedule"]["is_past"]:
            continue
        join = party_logic.list_row_join(p, summary, parties, discord_id, raids, now=now)
        if join["state"] != "can":
            continue
        view["join"] = join
        view["comp"] = party_logic.composition(p)
        view["fits"] = [o["name"] for o in join["options"]]
        out.append(view)
    out.sort(key=lambda p: p.get("scheduled_datetime") or "9999")
    return out


async def _safe(coro, default):
    """카드 하나의 봇 호출이 실패해도 홈 전체가 502로 떨어지지 않게 — 그 카드만 비운다."""
    try:
        return await coro
    except Exception:
        return default


# ── 숙제 ────────────────────────────────────────────────

def shown_difficulty(raid: dict, done_diff: str | None = None) -> str:
    """칸에 보여줄 난이도 — 클리어했으면 클리어한 난이도, 아니면 저장해 둔 난이도(preferred_difficulty),
    그것도 없거나 이제 그 캐릭터가 못 가는 난이도면 갈 수 있는 가장 높은 것(목록의 마지막)."""
    if done_diff:
        return done_diff
    diffs = raid.get("difficulties") or []
    pref = raid.get("preferred_difficulty")
    if pref in diffs:
        return pref
    return diffs[-1] if diffs else ""


def _done_difficulty(raid: dict, done_keys: set[str]) -> str | None:
    name = raid.get("raid_name")
    for d in raid.get("difficulties") or []:
        if f"{name}_{d}" in done_keys:
            return d
    # 레벨이 내려가 목록에서 빠진 난이도로 클리어한 기록도 "클리어"로 본다
    for key in done_keys:
        raid_name, _, diff = key.rpartition("_")
        if raid_name == name:
            return diff
    return None


def _recruit_link(ids: list[str]) -> str:
    return f"/parties/{ids[0]}" if len(ids) == 1 else "/parties?filter=eligible"


def build_homework(summary: dict, joinable: list[dict] | None = None) -> dict:
    """/raid-check-summary → 숙제 표시 모델.

    rows     — 캐릭터마다 그 캐릭터의 표시 레이드(visible_raid_names)만 칸(tiles)으로. 입장 가능한 레이드가 하나도
               없는 캐릭터는 뺀다. active(남은 숙제 있음)와 finished(이번 주 다 끝냄)로 나눈다.
    raids    — "레이드별" 보기: 레이드마다 그 레이드를 고른 캐릭터 칩 + 남은 수 + 참여 가능한 모집 수.
    칸의 recruit = 이 캐릭터가 이 레이드로 참여 가능한 모집 중 공대 수(joinable에서 센다).
    """
    joinable = joinable or []
    recruit: dict[tuple[str, str], list[str]] = {}
    raid_recruit: dict[str, list[str]] = {}
    for p in joinable:
        raid_recruit.setdefault(p["raid_name"], []).append(p["message_id"])
        for name in p.get("fits") or []:
            recruit.setdefault((p["raid_name"], name), []).append(p["message_id"])

    characters = summary.get("characters") or []
    rows = []
    raid_order: list[str] = []
    raid_map: dict[str, dict] = {}
    for ci, c in enumerate(characters):
        cname = c["character_name"]
        visible = set(c.get("visible_raid_names") or [])
        done_keys = set(c.get("completions") or [])
        tiles = []
        for r in c.get("applicable_raids") or []:
            rname = r.get("raid_name")
            if rname not in visible:
                continue
            diffs = list(r.get("difficulties") or [])
            done_diff = _done_difficulty(r, done_keys)
            ids = [] if done_diff else recruit.get((rname, cname), [])
            tile = {
                "raid_name": rname,
                "short_name": r.get("short_name") or rname,
                "category": r.get("category") or "",
                "diffs": diffs,
                "diff": shown_difficulty(r, done_diff),
                "done": done_diff is not None,
                "recruit": len(ids),
                "recruit_href": _recruit_link(ids) if ids else None,
                "menu_id": f"hwd-{ci}-{len(tiles)}",
            }
            tiles.append(tile)
            if rname not in raid_map:
                raid_map[rname] = {"raid_name": rname, "short_name": tile["short_name"], "category": tile["category"], "entries": []}
                raid_order.append(rname)
            raid_map[rname]["entries"].append({"char": cname, "diff": tile["diff"], "done": tile["done"]})
        if not tiles:
            continue
        done = sum(1 for t in tiles if t["done"])
        rows.append({
            "name": cname,
            "cls": c.get("character_class") or "",
            "item_level": c.get("item_level"),
            "tiles": tiles,
            "done": done,
            "total": len(tiles),
            "finished": done >= len(tiles),
            "ghosts": max(TILES_PER_ROW - len(tiles), 0),
            "select_href": f"/raid-check/select/{quote(cname)}",
        })

    raids = []
    for rname in raid_order:
        r = raid_map[rname]
        ids = raid_recruit.get(rname, [])
        left = sum(1 for e in r["entries"] if not e["done"])
        raids.append({
            **r,
            "left": left,
            "total": len(r["entries"]),
            "recruit": len(ids),
            "recruit_href": _recruit_link(ids) if ids else None,
            "create_href": f"/parties/create?raid={quote(rname)}",
        })

    done_sum = sum(r["done"] for r in rows)
    total_sum = sum(r["total"] for r in rows)
    return {
        "rows": rows,
        "active": [r for r in rows if not r["finished"]],
        "finished": [r for r in rows if r["finished"]],
        "raids": raids,
        "done": done_sum,
        "total": total_sum,
        "pct": round(done_sum / total_sum * 100) if total_sum else 0,
        "select_characters": [
            {"name": c["character_name"], "cls": c.get("character_class") or "", "item_level": c.get("item_level")}
            for c in characters
        ],
    }


def build_stats(homework: dict, schedule_count: int, joinable_count: int, now: datetime | None = None) -> list[dict]:
    """위쪽 숫자 카드 4장. 초기화는 하루 넘게 남았으면 일, 하루 안이면 시간(경고색)."""
    now = now or datetime.now(KST)
    remaining = next_reset(now) - now
    if remaining.days >= 1:
        reset_value, reset_unit, reset_tone = remaining.days, "일", ""
    else:
        reset_value, reset_unit, reset_tone = max(1, remaining.seconds // 3600), "시간", "warn"
    return [
        {"key": "homework", "label": "이번 주 숙제", "icon": "check", "value": homework["done"], "unit": f"/ {homework['total']}", "tone": "ok" if homework["total"] and homework["done"] >= homework["total"] else ""},
        {"key": "schedule", "label": "내 공대 일정", "icon": "clock", "value": schedule_count, "unit": "건", "tone": ""},
        {"key": "joinable", "label": "참여 가능 공대", "icon": "plus", "value": joinable_count, "unit": "개", "tone": ""},
        {"key": "reset", "label": "주간 초기화까지", "icon": "reset", "value": reset_value, "unit": reset_unit, "tone": reset_tone},
    ]


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



# 오늘의 콘텐츠 줄 순서 — 로아 API 순서(섬 → 카오스게이트 → 모험 섬 …)를 따르면 정작 많이 보는 모험섬이
# 세 번째로 밀린다. 여기 없는 종류는 "섬" 바로 앞에 API 순서대로 둔다.
TODAY_ORDER = ["모험섬", "필드보스", "카오스게이트", "태초의섬", "로웬", "항해"]
TODAY_LAST = "섬"


def _today_key(label: str, api_index: int) -> tuple:
    if label in TODAY_ORDER:
        return (0, TODAY_ORDER.index(label))
    if label == TODAY_LAST:
        return (2, 0)
    return (1, api_index)


def build_today(overview: dict, now: datetime | None = None) -> dict | None:
    """오늘의 콘텐츠(작은 카드) — 종류마다 한 줄: 다음에 시작하는 항목 이름(같은 시각에 여럿이면 "외 N")과 그 시각.
    같은 시각 항목 중 골드 섬이 있으면 그 이름을 앞에 두고 골드 표시. 오늘 일정이 다 지났으면 "오늘 끝남", 오늘 열리지 않는 날이면 "-"."""
    now = now or datetime.now(KST)
    items = overview.get("today") or []
    if not isinstance(items, list):
        return None
    groups: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        label = (it.get("category") or "기타").replace(" ", "")
        group = next((g for g in groups if g["label"] == label), None)
        if group is None:
            group = {"label": label, "items": []}
            groups.append(group)
        group["items"].append(it)
    if not groups:
        return None

    local_now = now.astimezone(KST)
    game_day_start = local_now.replace(hour=6, minute=0, second=0, microsecond=0)
    if local_now < game_day_start:
        game_day_start -= timedelta(days=1)
    rows = []
    for g in groups:
        had_times = False
        nexts = []
        for it in g["items"]:
            times = sorted(t for t in (_parse(x) for x in it.get("times") or []) if t)
            # 로아의 하루는 오전 6시에 바뀐다 — 0~6시 회차는 전날 콘텐츠의 연장이다(금요일 필드보스의 토요일 0시 회차 등).
            # 오늘(6시 이후) 열린 회차가 있었을 때만 "오늘 끝남", 아니면 오늘은 열리지 않는 날("-").
            had_times = had_times or any(t >= game_day_start for t in times)
            upcoming = next((t for t in times if t >= now), None)
            if upcoming:
                nexts.append((upcoming, it))
        if nexts:
            first = min(t for t, _ in nexts)
            same = [it for t, it in nexts if t == first]
            same.sort(key=lambda it: not it.get("is_gold"))  # 골드 섬을 대표로
            rows.append({
                "label": g["label"], "name": same[0].get("name") or "", "more": len(same) - 1,
                "time": first.strftime("%H:%M"), "rel": _until(first, now),
                "gold": any(it.get("is_gold") for it in same), "ended": False,
            })
        else:
            rows.append({
                "label": g["label"], "name": "오늘 끝남" if had_times else "-", "more": 0,
                "time": "", "rel": "", "gold": False, "ended": True,
            })
    rows = [r for _, r in sorted(enumerate(rows), key=lambda p: _today_key(p[1]["label"], p[0]))]
    return {"date": f"{now.month}/{now.day} ({'월화수목금토일'[now.weekday()]})", "rows": rows}

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
            "end_md": f"{end.month}/{end.day}" if end else "",
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
    parties = all_parties or []

    joinable = joinable_parties(parties, summary, discord_id)
    summary = summary or {}
    characters = summary.get("characters") or []
    mine = split_parties(parties, discord_id)
    overdue_mine = [
        {**party_view(p), "leader": leader_overview(p, discord_id)}
        for p in parties
        if p.get("leader_id") == discord_id and is_overdue_party(p)
    ]
    homework = build_homework(summary, joinable)
    schedule = build_schedule(mine, invites, discord_id)

    overview_ok = bool(overview.get("available"))
    return {
        "summary_failed": summary_failed,
        "has_characters": bool(characters),
        "homework": homework,
        "extreme": build_extreme(summary),
        "gold": build_gold(summary),
        "stats": build_stats(homework, len(schedule), len(joinable)),
        "invites": invites,
        "overdue_parties": overdue_mine,
        "todo_count": len(invites) + len(overdue_mine),
        "schedule": schedule[:PARTY_ROWS],
        "schedule_count": len(schedule),
        "opportunities": joinable[:PARTY_ROWS],
        "opportunity_count": len(joinable),
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


@router.post("/raid-check/difficulty-pref")
async def set_difficulty_pref(request: Request, user: dict = Depends(get_current_user)):
    """숙제 칸의 난이도(▾)를 바꾸면 home.js가 JSON {character_name, raid_name, difficulty}로 부른다.
    봇이 이 캐릭터·레이드에 그 난이도가 있는지, 내 캐릭터인지 확인한다(difficulty: null = 저장값 지우기).
    화면은 먼저 바꿔 두고(낙관적), 실패하면 되돌리고 토스트로 알린다."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"success": False, "reason": "잘못된 요청입니다."}, status_code=400)
    character_name, raid_name, difficulty = body.get("character_name"), body.get("raid_name"), body.get("difficulty")
    if not (isinstance(character_name, str) and character_name and isinstance(raid_name, str) and raid_name) \
            or not (difficulty is None or (isinstance(difficulty, str) and difficulty)):
        return JSONResponse({"success": False, "reason": "잘못된 요청입니다."}, status_code=400)
    try:
        result = await bot_home.set_raid_difficulty_pref(user["discord_id"], character_name, raid_name, difficulty)
    except httpx.HTTPError:
        return JSONResponse({"success": False, "reason": "봇 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요."}, status_code=502)
    if not result.get("success"):
        return JSONResponse({"success": False, "reason": result.get("reason") or "난이도를 저장하지 못했습니다."}, status_code=400)
    return {"success": True, "difficulty": result.get("difficulty", difficulty), "reason": None}

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
