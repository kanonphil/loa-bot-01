"""로스트아크 공용 데이터(공지·이벤트·캘린더·거래소 시세) 수집과 캐시.

길드원 개인 키의 한도를 쓰지 않도록 config.GUEST_LOOKUP_DISCORD_ID가 등록해 둔 키 하나만
쓴다(게스트 조회와 같은 키). 키가 없으면 모든 응답이 available=False + 한국어 reason.

- 공지/이벤트/캘린더: 30분마다, 수요일 05:30~10:30(KST, 정기 점검 시간대)에는 5분마다.
- 시세: 1시간마다.
- 503(점검 중)이면 그 주기의 나머지 호출은 건너뛰고 다음 주기까지 재시도하지 않는다.
- 마지막 정상 스냅샷은 loa_content_cache 테이블에 남겨 재시작해도 화면이 비지 않는다.

응답 구조는 실제 응답으로 검증된 게 아니라서(LOA-API-NOTES) 전부 .get()으로 방어적으로
읽고, 모양이 다르면 그 항목만 건너뛴다.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import config
import bot.api.lostark as loa
import bot.database.manager as db

KST = timezone(timedelta(hours=9))

CONTENT_INTERVAL = timedelta(minutes=30)
CONTENT_INTERVAL_MAINTENANCE = timedelta(minutes=5)
PRICE_INTERVAL = timedelta(hours=1)
GOLD_ISLAND_NOTICE_BEFORE = timedelta(minutes=10)
MAX_TRACKED_ITEMS = 8
TRACKED_ITEMS_KEY = "loa_tracked_items"

_SNAP_CONTENT = "content"
_SNAP_PRICES = "prices"
_SNAP_MARKET_OPTIONS = "market_options"

# 메모리 캐시 — 스냅샷과 같은 모양
_state: dict = {
    "content": None,          # {"notices", "events", "calendar", "fetched_at"}
    "prices": None,           # {"items", "fetched_at"}
    "outage": False,          # 마지막 주기에 503을 받았는지(다음 정상 응답에서 해제)
    "outage_at": None,
    "last_content_attempt": None,
    "last_price_attempt": None,
    "loaded": False,
    "market_categories": None,
}
_logged_calendar_names = False
_lock_holder: dict = {}


def _refresh_lock() -> asyncio.Lock:
    """이벤트 루프마다 하나 — 테스트처럼 asyncio.run을 여러 번 부르는 환경에서도 안전하게."""
    loop = asyncio.get_running_loop()
    if _lock_holder.get("loop") is not loop:
        _lock_holder["loop"] = loop
        _lock_holder["lock"] = asyncio.Lock()
    return _lock_holder["lock"]


# ── 공용 키 ───────────────────────────────────────────────

async def _server_key() -> tuple[str | None, str | None]:
    if not config.GUEST_LOOKUP_DISCORD_ID:
        return None, "서버 공용 로스트아크 API 키가 설정되지 않았습니다. 관리자에게 문의해주세요."
    key = await db.get_user_api_key(config.GUEST_LOOKUP_DISCORD_ID)
    if not key:
        return None, "서버 공용 로스트아크 API 키를 찾을 수 없습니다. 관리자에게 문의해주세요."
    return key, None


# ── 파싱 (전부 순수 함수 — 테스트 대상) ─────────────────────

def to_kst_iso(raw) -> str | None:
    """API 시각("2026-11-19T21:00:00", 오프셋 없음 = KST) → "2026-11-19T21:00:00+09:00"."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def _times_list(raw) -> list[str] | None:
    """StartTimes → KST ISO 리스트. null이면 None(= 항상/시간 무관)."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw:
        iso = to_kst_iso(t)
        if iso and iso not in out:
            out.append(iso)
    return sorted(out)


def _raw_reward_items(entry: dict) -> list[dict]:
    """RewardItems의 두 가지 모양을 모두 받는다 — [{ItemLevel, Items:[...]}](현행) 또는
    [{Name, Icon, Grade, StartTimes}](구버전)."""
    out: list[dict] = []
    for group in entry.get("RewardItems") or []:
        if not isinstance(group, dict):
            continue
        if isinstance(group.get("Items"), list):
            out.extend(i for i in group["Items"] if isinstance(i, dict))
        elif group.get("Name"):
            out.append(group)
    return out


def normalize_calendar(raw) -> list[dict]:
    """GET /gamecontents/calendar 원본 → 저장용 정규화 목록."""
    result = []
    if not isinstance(raw, list):
        return result
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            min_level = float(str(entry.get("MinItemLevel") or 0).replace(",", ""))
        except (TypeError, ValueError):
            min_level = 0
        rewards = []
        for item in _raw_reward_items(entry):
            name = item.get("Name")
            if not name:
                continue
            rewards.append({
                "name": str(name),
                "icon": item.get("Icon"),
                "grade": item.get("Grade"),
                "times": _times_list(item.get("StartTimes")),
            })
        result.append({
            "category": str(entry.get("CategoryName") or ""),
            "name": str(entry.get("ContentsName") or ""),
            "icon": entry.get("ContentsIcon"),
            "min_item_level": int(min_level) if float(min_level).is_integer() else min_level,
            "times": _times_list(entry.get("StartTimes")) or [],
            "rewards": rewards,
        })
    return result


def is_gold_island(category: str, reward_names) -> bool:
    """골드 섬 판정 — 카테고리에 "모험"이 들어가고, 그날 보상 중 이름에 "골드"가 들어간
    아이템이 있으면 골드 섬. 실제 이름이 다르면(로그에 남긴 원본 이름 참고) 여기만 고친다."""
    if "모험" not in (category or ""):
        return False
    return any("골드" in (n or "") for n in reward_names)


def items_for_date(calendar: list[dict], date: str) -> list[dict]:
    """정규화된 캘린더에서 date(YYYY-MM-DD)에 열리는 콘텐츠만, 그날 시각·보상으로 좁혀서."""
    out = []
    for entry in calendar or []:
        times = [t for t in entry.get("times") or [] if t.startswith(date)]
        if not times:
            continue
        rewards = []
        seen = set()
        for r in entry.get("rewards") or []:
            rtimes = r.get("times")
            if rtimes is not None and not any(t.startswith(date) for t in rtimes):
                continue
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            rewards.append({"name": r["name"], "icon": r.get("icon"), "grade": r.get("grade")})
        out.append({
            "category": entry.get("category") or "",
            "name": entry.get("name") or "",
            "icon": entry.get("icon"),
            "min_item_level": entry.get("min_item_level") or 0,
            "times": times,
            "rewards": rewards,
            "is_gold": is_gold_island(entry.get("category") or "", [r["name"] for r in rewards]),
        })
    out.sort(key=lambda e: (e["times"][0], e["category"], e["name"]))
    return out


def _log_calendar_names_once(calendar: list[dict]) -> None:
    """골드 섬 판정 기준을 관리자가 맞출 수 있게, 처음 받은 캘린더의 카테고리명과
    모험 섬 보상 이름을 한 번만 로그로 남긴다."""
    global _logged_calendar_names
    if _logged_calendar_names or not calendar:
        return
    _logged_calendar_names = True
    categories = sorted({e["category"] for e in calendar if e.get("category")})
    island_rewards = sorted({
        r["name"] for e in calendar if "모험" in (e.get("category") or "") for r in e.get("rewards") or []
    })
    print(f"[loa_content] 캘린더 카테고리: {', '.join(categories)}")
    print(f"[loa_content] 모험 섬 보상 이름: {', '.join(island_rewards[:60])}")


def parse_notices(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for n in raw:
        if not isinstance(n, dict) or not n.get("Title"):
            continue
        out.append({
            "title": str(n.get("Title")),
            "date": to_kst_iso(n.get("Date")),
            "link": n.get("Link"),
            "type": n.get("Type") or "",
        })
    return out


def _merge_notices(*lists: list[dict]) -> list[dict]:
    seen = set()
    merged = []
    for lst in lists:
        for n in lst:
            key = n.get("link") or n["title"]
            if key in seen:
                continue
            seen.add(key)
            merged.append(n)
    merged.sort(key=lambda n: n.get("date") or "", reverse=True)
    return merged


def parse_events(raw, now: datetime) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for e in raw:
        if not isinstance(e, dict) or not e.get("Title"):
            continue
        end = to_kst_iso(e.get("EndDate"))
        if end and datetime.fromisoformat(end) < now:
            continue
        out.append({
            "title": str(e.get("Title")),
            "thumbnail": e.get("Thumbnail"),
            "link": e.get("Link"),
            "start": to_kst_iso(e.get("StartDate")),
            "end": end,
        })
    return out


_TITLE_DATE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_TITLE_TIMES = re.compile(r"(\d{1,2}):(\d{2})\s*[~∼\-]\s*(\d{1,2}):(\d{2})")


def detect_maintenance(notices: list[dict], now: datetime, outage: bool) -> dict | None:
    """점검 공지(유형 '점검' 또는 제목에 '점검') 중 가장 최근 것으로 점검 정보를 만든다.
    제목의 "11월 19일" / "06:00 ~ 10:00"을 읽고, 시각이 없는 수요일 점검은 06:00 시작으로
    본다. 503을 받은 상태(outage)면 공지가 없어도 active=True, title="점검 중"."""
    candidate = None
    for n in notices:
        if n.get("type") == "점검" or "점검" in (n.get("title") or ""):
            posted = n.get("date")
            if posted and datetime.fromisoformat(posted) < now - timedelta(days=7):
                continue
            candidate = n
            break

    if candidate is None:
        if outage:
            return {"active": True, "title": "점검 중", "starts_at": None, "ends_at": None, "link": None}
        return None

    title = candidate.get("title") or ""
    posted = datetime.fromisoformat(candidate["date"]) if candidate.get("date") else now
    day = posted.date()
    m = _TITLE_DATE.search(title)
    if m:
        month, dom = int(m.group(1)), int(m.group(2))
        year = now.year
        if month < now.month - 6:
            year += 1
        elif month > now.month + 6:
            year -= 1
        try:
            day = datetime(year, month, dom, tzinfo=KST).date()
        except ValueError:
            pass
    starts = ends = None
    t = _TITLE_TIMES.search(title)
    if t:
        try:
            starts = datetime(day.year, day.month, day.day, int(t.group(1)), int(t.group(2)), tzinfo=KST)
            ends = datetime(day.year, day.month, day.day, int(t.group(3)), int(t.group(4)), tzinfo=KST)
            if ends <= starts:
                ends += timedelta(days=1)
        except ValueError:
            starts = ends = None
    elif day.weekday() == 2:
        starts = datetime(day.year, day.month, day.day, 6, 0, tzinfo=KST)

    window_end = ends or (starts + timedelta(hours=4) if starts else None)
    active = outage or bool(starts and starts <= now < window_end)
    # 시각을 알면 끝나기 전까지, 모르면 그날이 지나기 전까지 보여준다
    upcoming = now < window_end if window_end else day >= now.date()
    if not (active or upcoming):
        return None
    return {
        "active": active,
        "title": title,
        "starts_at": starts.isoformat() if starts else None,
        "ends_at": ends.isoformat() if ends else None,
        "link": candidate.get("link"),
    }


def _content_interval(now: datetime) -> timedelta:
    """수요일 05:30~10:30은 점검 공지를 빨리 반영하려고 5분, 그 외 30분."""
    if now.weekday() == 2:
        minutes = now.hour * 60 + now.minute
        if 5 * 60 + 30 <= minutes < 10 * 60 + 30:
            return CONTENT_INTERVAL_MAINTENANCE
    return CONTENT_INTERVAL


# ── 스냅샷 로드/저장 ─────────────────────────────────────────

async def _load_snapshots() -> None:
    if _state["loaded"]:
        return
    _state["loaded"] = True
    for key in (_SNAP_CONTENT, _SNAP_PRICES, _SNAP_MARKET_OPTIONS):
        try:
            snap = await db.get_content_snapshot(key)
        except Exception as e:
            print(f"[loa_content] 스냅샷 읽기 실패({key}): {e}")
            continue
        if not snap or not isinstance(snap.get("payload"), (dict, list)):
            continue
        fetched = _parse_iso(snap.get("fetched_at"))
        # 이미 메모리에 있는 값(이번 실행에서 받은 것)은 덮어쓰지 않는다
        if key == _SNAP_CONTENT and isinstance(snap["payload"], dict):
            if _state["content"] is None:
                _state["content"] = snap["payload"]
            if _state["last_content_attempt"] is None:
                _state["last_content_attempt"] = fetched
        elif key == _SNAP_PRICES and isinstance(snap["payload"], dict):
            if _state["prices"] is None:
                _state["prices"] = snap["payload"]
            if _state["last_price_attempt"] is None:
                _state["last_price_attempt"] = fetched
        elif key == _SNAP_MARKET_OPTIONS and isinstance(snap["payload"], list):
            if not _state["market_categories"]:
                _state["market_categories"] = snap["payload"]


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)


def _now() -> datetime:
    return datetime.now(KST)


# ── 수집 ──────────────────────────────────────────────────

def _mark_outage(now: datetime) -> None:
    if not _state["outage"]:
        print("[loa_content] 503 — 점검 중으로 표시, 다음 주기까지 재시도하지 않음")
    _state["outage"] = True
    _state["outage_at"] = now.isoformat()


async def refresh_content(now: datetime | None = None) -> bool:
    """공지·이벤트·캘린더를 새로 받는다. 하나라도 받으면 스냅샷 저장 후 True.
    503이면 나머지 호출을 건너뛰고 False(이전 스냅샷은 그대로)."""
    now = now or _now()
    key, _reason = await _server_key()
    _state["last_content_attempt"] = now
    if not key:
        return False

    prev = _state["content"] or {}
    notices = events = calendar = None
    try:
        all_notices = parse_notices(await loa.get_notices(key))
        maint_notices = parse_notices(await loa.get_notices(key, "점검"))
        notices = _merge_notices(all_notices, maint_notices)
        events = parse_events(await loa.get_events(key), now)
        calendar = normalize_calendar(await loa.get_calendar(key))
    except loa.LoaMaintenanceError:
        _mark_outage(now)
        return False
    except RuntimeError as e:
        print(f"[loa_content] 공지/캘린더 수집 실패: {e}")
    except Exception as e:  # 응답 모양이 예상과 다를 때 루프가 죽지 않게
        print(f"[loa_content] 공지/캘린더 파싱 실패: {type(e).__name__}: {e}")

    if notices is None and events is None and calendar is None:
        return False
    _state["outage"] = False
    if calendar:
        _log_calendar_names_once(calendar)
    content = {
        "notices": notices if notices is not None else prev.get("notices", []),
        "events": events if events is not None else prev.get("events", []),
        # 빈 캘린더(응답 이상)로 기존 캘린더를 덮어쓰지 않는다
        "calendar": calendar if calendar else prev.get("calendar", []),
        "fetched_at": now.isoformat(),
    }
    _state["content"] = content
    await db.set_content_snapshot(_SNAP_CONTENT, content, content["fetched_at"])
    return True


async def get_tracked_items() -> list[str]:
    raw = await db.get_setting(TRACKED_ITEMS_KEY)
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(n) for n in names if isinstance(n, str) and n.strip()][:MAX_TRACKED_ITEMS]


def clean_tracked_names(names) -> list[str]:
    out = []
    for n in names or []:
        n = str(n).strip()
        if n and n not in out:
            out.append(n)
    return out


async def _market_categories(key: str) -> list[int]:
    """GET /markets/options의 최상위 카테고리 코드 — 한 번 받아 스냅샷으로 보관."""
    if _state["market_categories"]:
        return _state["market_categories"]
    raw = await loa.get_market_options(key)
    codes = []
    categories = raw.get("Categories") if isinstance(raw, dict) else None
    for c in categories or []:
        code = c.get("Code") if isinstance(c, dict) else None
        if isinstance(code, int) and code not in codes:
            codes.append(code)
    if codes:
        _state["market_categories"] = codes
        await db.set_content_snapshot(_SNAP_MARKET_OPTIONS, codes, _now().isoformat())
    return codes


def _exact_match(result, name: str) -> dict | None:
    items = (result or {}).get("Items") if isinstance(result, dict) else None
    for it in items or []:
        if isinstance(it, dict) and it.get("Name") == name and it.get("Id") is not None:
            return it
    return None


async def resolve_item(key: str, name: str) -> dict | None:
    """이름이 정확히 같은 거래소 아이템을 카테고리별로 찾아 id를 저장한다. 못 찾으면 None."""
    for code in await _market_categories(key):
        found = _exact_match(await loa.search_market_items(key, name, code), name)
        if found:
            await db.set_market_item_id(name, int(found["Id"]), code, found.get("Icon"))
            return {"name": name, "item_id": int(found["Id"]), "category_code": code, "icon": found.get("Icon")}
    return None


async def resolve_tracked_items(names: list[str], deadline: float = 12.0) -> list[str]:
    """아직 id를 모르는 이름을 찾아 저장하고, 못 찾은 이름 목록을 돌려준다.
    시간 안에 다 못 찾은 이름도 못 찾은 쪽에 넣는다(다음 시세 갱신 때 다시 시도)."""
    key, _ = await _server_key()
    known = await db.get_market_item_ids()
    pending = [n for n in names if n not in known]
    if not pending:
        return []
    if not key:
        return pending
    unresolved: list[str] = []

    async def work():
        for n in pending:
            try:
                if await resolve_item(key, n) is None:
                    unresolved.append(n)
            except loa.LoaMaintenanceError:
                _mark_outage(_now())
                unresolved.extend(x for x in pending if x not in unresolved and x not in known)
                return
            except RuntimeError as e:
                print(f"[loa_content] 아이템 검색 실패({n}): {e}")
                unresolved.append(n)

    try:
        await asyncio.wait_for(work(), timeout=deadline)
    except asyncio.TimeoutError:
        known = await db.get_market_item_ids()
        unresolved = [n for n in pending if n not in known]
    return [n for n in pending if n in set(unresolved)]


def _history(raw) -> list[dict]:
    entries = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    for e in entries:
        stats = e.get("Stats") if isinstance(e, dict) else None
        if not isinstance(stats, list):
            continue
        out = []
        for s in stats:
            if not isinstance(s, dict) or not s.get("Date"):
                continue
            try:
                out.append({"date": str(s["Date"])[:10], "avg": float(s.get("AvgPrice") or 0)})
            except (TypeError, ValueError):
                continue
        return sorted(out, key=lambda h: h["date"])
    return []


async def refresh_prices(now: datetime | None = None) -> bool:
    now = now or _now()
    _state["last_price_attempt"] = now
    key, _ = await _server_key()
    if not key:
        return False
    names = await get_tracked_items()
    prev_items = {i["name"]: i for i in (_state["prices"] or {}).get("items", [])}
    items: list[dict] = []
    try:
        outage_before = _state["outage_at"]
        await resolve_tracked_items(names)
        if _state["outage_at"] != outage_before:  # 이번 주기에 503 — 나머지 호출은 건너뛴다
            return False
        known = await db.get_market_item_ids()
        for name in names:
            info = known.get(name)
            if not info:
                continue
            try:
                found = _exact_match(
                    await loa.search_market_items(key, name, info.get("category_code") or 0), name
                )
                hist = _history(await loa.get_market_item(key, info["item_id"]))
            except loa.LoaMaintenanceError:
                raise
            except RuntimeError as e:
                print(f"[loa_content] 시세 조회 실패({name}): {e}")
                if name in prev_items:
                    items.append(prev_items[name])
                continue
            if found is None and name in prev_items:
                items.append(prev_items[name])
                continue
            current = int((found or {}).get("CurrentMinPrice") or 0)
            yday = float((found or {}).get("YDayAvgPrice") or 0)
            items.append({
                "id": info["item_id"],
                "name": name,
                "icon": (found or {}).get("Icon") or info.get("icon"),
                "current": current,
                "yday_avg": yday,
                "change_pct": round((current - yday) / yday * 100, 2) if yday > 0 else 0.0,
                "history": hist,
            })
    except loa.LoaMaintenanceError:
        _mark_outage(now)
        return False
    except Exception as e:
        print(f"[loa_content] 시세 수집 실패: {type(e).__name__}: {e}")
        return False

    _state["outage"] = False
    prices = {"items": items, "fetched_at": now.isoformat()}
    _state["prices"] = prices
    await db.set_content_snapshot(_SNAP_PRICES, prices, prices["fetched_at"])
    return True


async def tick(now: datetime | None = None) -> None:
    """봇 루프(1분)에서 호출 — 갱신 주기가 된 것만 받는다."""
    now = now or _now()
    async with _refresh_lock():
        await _load_snapshots()
        last = _state["last_content_attempt"]
        if last is None or now - last >= _content_interval(now):
            await refresh_content(now)
        last = _state["last_price_attempt"]
        if last is None or now - last >= PRICE_INTERVAL:
            await refresh_prices(now)


# ── 응답 조립 ─────────────────────────────────────────────

def _unavailable_reason(content: dict | None) -> str:
    if _state["outage"]:
        return "로스트아크 점검 중이라 정보를 불러올 수 없습니다."
    return "아직 로스트아크 정보를 불러오지 못했습니다. 잠시 후 다시 확인해주세요."


async def overview(discord_id: str, now: datetime | None = None) -> dict:
    now = now or _now()
    await _load_snapshots()
    subscribed = await db.is_gold_island_subscribed(discord_id) if discord_id else False
    key, reason = await _server_key()
    content = _state["content"]
    out = {
        "available": False,
        "reason": reason,
        "fetched_at": None,
        "maintenance": None,
        "notices": [],
        "events": [],
        "today": [],
        "gold_island_subscribed": subscribed,
    }
    if not key:
        return out
    if not content:
        out["reason"] = _unavailable_reason(content)
        out["maintenance"] = detect_maintenance([], now, _state["outage"])
        return out
    out.update({
        "available": True,
        "reason": None,
        "fetched_at": content.get("fetched_at"),
        "maintenance": detect_maintenance(content.get("notices") or [], now, _state["outage"]),
        "notices": (content.get("notices") or [])[:5],
        "events": content.get("events") or [],
        "today": items_for_date(content.get("calendar") or [], now.date().isoformat()),
    })
    return out


async def calendar_for(date: str | None, now: datetime | None = None) -> dict:
    now = now or _now()
    await _load_snapshots()
    day = date or now.date().isoformat()
    try:
        day = datetime.fromisoformat(day).date().isoformat()
    except ValueError:
        return {"available": False, "date": date, "items": [], "reason": "날짜 형식이 올바르지 않습니다."}
    key, reason = await _server_key()
    content = _state["content"]
    if not key or not content:
        return {"available": False, "date": day, "items": [], "reason": reason or _unavailable_reason(content)}
    return {"available": True, "date": day, "items": items_for_date(content.get("calendar") or [], day)}


async def prices() -> dict:
    await _load_snapshots()
    key, reason = await _server_key()
    snap = _state["prices"]
    if not key:
        return {"available": False, "fetched_at": None, "items": [], "reason": reason}
    names = await get_tracked_items()
    if not names:
        return {"available": True, "fetched_at": (snap or {}).get("fetched_at"), "items": []}
    if not snap:
        return {"available": False, "fetched_at": None, "items": [], "reason": _unavailable_reason(None)}
    by_name = {i["name"]: i for i in snap.get("items") or []}
    return {
        "available": True,
        "fetched_at": snap.get("fetched_at"),
        "items": [by_name[n] for n in names if n in by_name],
    }


async def set_tracked_items(names: list[str]) -> tuple[list[str], list[str]]:
    """추적 아이템 저장(최대 8개) + 즉시 id 찾기. (저장된 이름, 못 찾은 이름).
    저장 후 시세를 백그라운드로 다시 받아 화면에 바로 반영되게 한다."""
    cleaned = clean_tracked_names(names)[:MAX_TRACKED_ITEMS]
    await db.set_setting(TRACKED_ITEMS_KEY, json.dumps(cleaned, ensure_ascii=False))
    unresolved = await resolve_tracked_items(cleaned)
    _schedule_price_refresh()
    return cleaned, unresolved


_bg_tasks: set = set()


def _schedule_price_refresh() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def runner():
        try:
            async with _refresh_lock():
                await refresh_prices()
        except Exception as e:
            print(f"[loa_content] 시세 갱신 실패: {type(e).__name__}: {e}")

    task = loop.create_task(runner())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


# ── 골드 섬 DM ────────────────────────────────────────────

def first_gold_island(calendar: list[dict], now: datetime) -> tuple[datetime, list[str]] | None:
    """오늘 첫 골드 섬 시작 시각과 그 시각에 열리는 골드 섬 이름들."""
    today = now.date().isoformat()
    best: datetime | None = None
    names: list[str] = []
    for item in items_for_date(calendar, today):
        if not item["is_gold"]:
            continue
        for t in item["times"]:
            dt = datetime.fromisoformat(t)
            if best is None or dt < best:
                best, names = dt, [item["name"]]
            elif dt == best and item["name"] not in names:
                names.append(item["name"])
    return (best, names) if best else None


async def gold_island_dm_tick(bot, now: datetime | None = None) -> int:
    """오늘 첫 골드 섬 10분 전 구간이면 구독자에게 DM(하루 한 번). 보낸 수를 돌려준다.
    봇이 그 구간에 꺼져 있었으면 시작 뒤에 늦게 보내지 않는다."""
    if bot is None:
        return 0
    now = now or _now()
    await _load_snapshots()
    content = _state["content"]
    if not content:
        return 0
    found = first_gold_island(content.get("calendar") or [], now)
    if not found:
        return 0
    start, names = found
    if not (start - GOLD_ISLAND_NOTICE_BEFORE <= now < start):
        return 0
    today = now.date().isoformat()
    targets = await db.get_gold_island_dm_targets(today)
    if not targets:
        return 0
    from bot.ui.views import _send_dm

    minutes = max(1, int((start - now).total_seconds() // 60))
    text = (
        f"오늘 첫 골드 섬이 {minutes}분 뒤({start.strftime('%H:%M')}) 시작합니다.\n"
        f"{', '.join(names)}"
    )
    sent = 0
    for discord_id in targets:
        try:
            await _send_dm(bot, discord_id, text, kind="gold_island")
            sent += 1
        except Exception as e:
            print(f"[골드 섬 알림] 발송 실패 (discord_id={discord_id}): {type(e).__name__}: {e}")
        finally:
            await db.mark_gold_island_dm_sent(discord_id, today)
    return sent


def _reset_state_for_tests() -> None:
    global _logged_calendar_names
    _state.update({
        "content": None, "prices": None, "outage": False, "outage_at": None,
        "last_content_attempt": None, "last_price_attempt": None, "loaded": False,
        "market_categories": None,
    })
    _logged_calendar_names = False
