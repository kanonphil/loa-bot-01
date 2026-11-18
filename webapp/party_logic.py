"""공대 화면의 판단 로직 — 봇이 이미 돌려주는 데이터(캐릭터, 이번 주 완료, 내 다른 공대)로
"이 캐릭터가 이 공대에 들어갈 수 있나 / 어떤 캐릭터를 추천하나"를 웹에서 계산한다.
템플릿과 라우트에서 날짜·자격 계산을 하지 않도록 순수 함수로 모았고, "지금"은 인자로 받는다.

봇의 참여 규칙(bot/database/manager.py get_party_eligibility)과 같은 기준을 따라가되,
최종 판정은 항상 봇이 한다 — 여기 결과는 "어느 캐릭터를 먼저 보여줄지"와 "왜 안 되는지 미리 보여주기"용이다."""
from __future__ import annotations

from datetime import datetime, timedelta

from webapp.format import KST, _parse, next_reset

# 같은 캐릭터가 이 간격 안의 다른 공대에 있으면 같은 시간으로 본다
CONFLICT_WINDOW = timedelta(hours=2)
# 같은 레이드·난이도 공대가 이 간격 안에 모집 중이면 개설 전에 알려준다
DUPLICATE_WINDOW = timedelta(hours=1)
ACTIVE_STATUSES = ("recruiting", "full", "closed")

STATUS_LABELS: dict[str, tuple[str, str]] = {
    "recruiting": ("모집중", "accent"),
    "full": ("파티완성", "warn"),
    "closed": ("마감", ""),
    "disbanded": ("종료", ""),
    "cleared": ("클리어", "ok"),
    "expired": ("기한 만료", "past"),
    "cancelled": ("취소", "danger"),
}


def status_view(party: dict) -> tuple[str, str]:
    """(라벨, 톤). 클리어(cleared_at이 찍힘)와 관리자 종료(disbanded인데 cleared_at 없음)를 구분한다."""
    status = party.get("status")
    if status == "disbanded" and party.get("cleared_at"):
        status = "cleared"
    return STATUS_LABELS.get(status, (str(status or ""), ""))


def is_ended(party: dict) -> bool:
    return party.get("status") in ("disbanded", "expired")


# ── 주간 리셋 ────────────────────────────────────────────

def week_start(dt: datetime) -> datetime:
    """dt가 속한 주의 시작 — 가장 가까운 지난 수요일 06:00(KST)."""
    dt = dt.astimezone(KST)
    start = (dt - timedelta(days=(dt.weekday() - 2) % 7)).replace(hour=6, minute=0, second=0, microsecond=0)
    if start > dt:
        start -= timedelta(days=7)
    return start


def reset_info(target: datetime | None, now: datetime | None = None) -> dict:
    """일정 선택 화면의 "리셋까지 N일" 안내와 "다음 주 숙제" 경고."""
    now = now or datetime.now(KST)
    reset = next_reset(now)
    remaining = reset - now
    if remaining >= timedelta(days=1):
        left = f"{remaining.days}일"
    else:
        hours = max(1, remaining.seconds // 3600)
        left = f"{hours}시간"
    return {
        "label": f"리셋까지 {left} · 수요일 06:00",
        "reset_iso": reset.isoformat(),
        "next_week": bool(target and target >= reset),
    }


# ── 파티 구성 ────────────────────────────────────────────

def composition(party: dict) -> dict:
    """딜러/서포터 현황. 서포터 자리는 4인 파티마다 1명(8인 = 2, 16인 = 4)."""
    total = party.get("total_slots") or 0
    slots = party.get("slots") or []
    sup_total = max(1, total // 4) if total else 0
    dps_total = max(0, total - sup_total)
    sup = sum(1 for s in slots if s.get("role") == "support")
    dps = len(slots) - sup
    return {
        "dps": dps, "dps_total": dps_total, "sup": sup, "sup_total": sup_total,
        "lacks_support": sup < sup_total, "lacks_dps": dps < dps_total,
        "filled": len(slots), "total": total,
    }


def group_layout(party: dict, party_split: int | None) -> list[dict]:
    """파티 그룹별 자리. 분할이 없으면 그룹 1개. 각 자리는 slot_number(절대)와 local_number(그룹 안 번호)를 가진다."""
    total = party.get("total_slots") or 0
    by_number = {s["slot_number"]: s for s in party.get("slots") or []}
    split = party_split if party_split and total > party_split else total
    count = max(1, total // split) if split else 1
    groups = []
    for g in range(1, count + 1):
        start = (g - 1) * split + 1
        slots = []
        for local in range(1, split + 1):
            absolute = start + local - 1
            slot = by_number.get(absolute)
            if slot:
                slots.append({**slot, "local_number": local, "filled": True})
            else:
                slots.append({"slot_number": absolute, "local_number": local, "filled": False})
        filled = [s for s in slots if s["filled"]]
        groups.append({
            "group_number": g, "slots": slots, "filled_count": len(filled), "total": split,
            "has_support": any(s.get("role") == "support" for s in filled),
            "free": split - len(filled),
        })
    return groups


def pick_group(groups: list[dict], role: str) -> int | None:
    """참여할 파티 그룹을 자동으로 고른다. 서포터는 서포터가 없는 파티를 먼저, 딜러는 서포터가 이미
    있는 파티를 먼저 채워 파티마다 서포터 한 명이 들어갈 자리를 남긴다."""
    open_groups = [g for g in groups if g["free"] > 0]
    if not open_groups:
        return None
    if role == "support":
        for g in open_groups:
            if not g["has_support"]:
                return g["group_number"]
        return open_groups[0]["group_number"]
    for g in open_groups:
        # 서포터 자리를 비워 둘 만큼은 남겨야 딜러가 들어간다
        if g["has_support"] or g["free"] > 1:
            return g["group_number"]
    return open_groups[0]["group_number"]


# ── 캐릭터 추천 ──────────────────────────────────────────

def _party_dt(party: dict) -> datetime | None:
    return _parse(party.get("scheduled_datetime"))


def my_party_slots(parties: list[dict], discord_id: str, exclude_id: str | None = None) -> list[dict]:
    """내가 참여 중인 진행 중 공대마다 (공대, 내 캐릭터 이름)."""
    out = []
    for p in parties:
        if p.get("status") not in ACTIVE_STATUSES or p.get("message_id") == exclude_id:
            continue
        for s in p.get("slots") or []:
            if s.get("discord_id") == discord_id:
                out.append({"party": p, "character_name": s.get("character_name")})
    return out


def character_options(
    summary: dict | None,
    *,
    raid_name: str,
    difficulty: str,
    min_level: float,
    target: datetime | None,
    my_slots: list[dict],
    lacks_support: bool = False,
    is_extreme: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    """내 캐릭터별 참여 가능 여부. 추천 순서(가능한 것 먼저 → 서포터가 부족하면 서포터 우선 → 아이템 레벨 높은 순)로 정렬해
    돌려준다. 항목: name, cls, level, is_support, role, ok(참여 가능), reason(안 되는 이유), note(참고 문구), recommended.
    summary가 없으면(봇 조회 실패) 빈 목록."""
    if not summary:
        return []
    now = now or datetime.now(KST)
    cur_week = week_start(now)
    target_week = week_start(target) if target else cur_week
    same_week = target_week == cur_week  # 이번 주 완료 기록은 이번 주 공대에서만 의미가 있다

    extreme_info = next(
        (e for e in summary.get("extreme") or [] if e.get("raid_name") == raid_name), None
    ) if is_extreme else None
    extreme_cleared = bool(extreme_info and extreme_info.get("cleared")) and same_week

    options = []
    for c in summary.get("characters") or []:
        name = c.get("character_name")
        level = c.get("item_level")
        reason = None
        note = None
        if level is None:
            reason = "아이템 레벨 미확인"
        elif level < min_level:
            reason = f"레벨 {int(min_level)} 필요"
        elif is_extreme:
            if extreme_cleared:
                reason = "원정대 주 1회 · 이미 감"
            else:
                note = "원정대 주 1회 · 아직 안 감"
        elif same_week and any(
            key.rsplit("_", 1)[0] == raid_name for key in c.get("completions") or []
        ):
            reason = "이번 주 완료"
        if reason is None:
            for other in my_slots:
                if other["character_name"] != name:
                    continue
                other_dt = _party_dt(other["party"])
                if target and other_dt and abs(other_dt - target) < CONFLICT_WINDOW:
                    reason = "같은 시간 다른 공대"
                    break
                if (other["party"].get("raid_name") == raid_name and other_dt and target
                        and week_start(other_dt) == target_week):
                    reason = "이번 주 이 레이드의 다른 공대"
                    break
        is_support = bool(c.get("is_support"))
        options.append({
            "name": name, "cls": c.get("character_class"), "level": level,
            "is_support": is_support, "role": "support" if is_support else "dps",
            "ok": reason is None, "reason": reason, "note": note, "recommended": False,
        })

    def rank(o: dict):
        support_first = lacks_support and o["is_support"]
        return (not o["ok"], not support_first, -(o["level"] or 0))

    options.sort(key=rank)
    for o in options:
        if o["ok"]:
            o["recommended"] = True
            break
    return options


def join_summary(options: list[dict]) -> dict:
    """목록의 참여 칸이 보여줄 것. 가능한 캐릭터가 있으면 options, 없으면 대표 이유 하나."""
    ok = [o for o in options if o["ok"]]
    if ok:
        return {"can_join": True, "options": ok, "reason": None}
    reasons = [o["reason"] for o in options if o.get("reason")]
    if not options:
        return {"can_join": False, "options": [], "reason": "참여할 캐릭터가 없습니다"}
    # 모두 같은 이유면 그대로, 아니면 가장 흔한 이유를 대표로
    top = max(set(reasons), key=reasons.count) if reasons else "참여할 수 없습니다"
    if top == "이번 주 완료" and len(set(reasons)) == 1:
        top = "모든 캐릭터가 이번 주 완료"
    return {"can_join": False, "options": [], "reason": top}


def list_row_join(
    party: dict, summary: dict | None, parties: list[dict], discord_id: str, raids: dict,
    now: datetime | None = None,
) -> dict:
    """공대 목록 한 줄의 참여 칸 상태. state: joined / leader / full / closed / ended / can / blocked / unknown."""
    status = party.get("status")
    slots = party.get("slots") or []
    if is_ended(party):
        return {"state": "ended"}
    if party.get("leader_id") == discord_id or any(s.get("discord_id") == discord_id for s in slots):
        return {"state": "joined"}
    if status == "closed":
        return {"state": "closed"}
    comp = composition(party)
    if status == "full" or (comp["total"] and comp["filled"] >= comp["total"]):
        return {"state": "full"}
    if summary is None:
        return {"state": "unknown"}
    raid_info = raids.get(party.get("raid_name")) or {}
    diff = (raid_info.get("difficulties") or {}).get(party.get("difficulty")) or {}
    result = join_summary(character_options(
        summary,
        raid_name=party.get("raid_name"), difficulty=party.get("difficulty"),
        min_level=party.get("min_level") or 0, target=_party_dt(party),
        my_slots=my_party_slots(parties, discord_id, exclude_id=party.get("message_id")),
        lacks_support=comp["lacks_support"], is_extreme=bool(raid_info.get("is_extreme")), now=now,
    ))
    if not result["can_join"]:
        return {"state": "blocked", "reason": result["reason"]}
    split = diff.get("party_split")
    groups = group_layout(party, split)
    for o in result["options"]:
        # 역할: 서포터 직업이어도 서포터 자리가 이미 다 찼으면 딜러로
        o["role"] = "support" if o["is_support"] and comp["lacks_support"] else "dps"
        o["group"] = pick_group(groups, o["role"]) if len(groups) > 1 else None
    return {"state": "can", "options": result["options"], "split": bool(split)}


# ── 개설 전 안내 ─────────────────────────────────────────

def find_duplicates(
    parties: list[dict], raid_name: str, difficulty: str, target: datetime | None,
) -> list[dict]:
    """같은 레이드·난이도로 target ±1시간 안에 모집 중인 공대."""
    if not target:
        return []
    found = []
    for p in parties:
        if p.get("status") != "recruiting":
            continue
        if p.get("raid_name") != raid_name or p.get("difficulty") != difficulty:
            continue
        dt = _party_dt(p)
        if dt and abs(dt - target) <= DUPLICATE_WINDOW:
            found.append(p)
    return found


def time_presets(now: datetime | None = None) -> list[dict]:
    """일정 프리셋 — 오늘 21:00 · 내일 21:00 · 이번 주 토 21:00 (이미 지났으면 다음 토요일).
    value는 폼이 제출하는 형식(Y-m-d\\TH:i). 오늘 21:00이 이미 지났으면 그 칩은 뺀다."""
    now = now or datetime.now(KST)
    fmt = "%Y-%m-%dT%H:%M"
    names = ["월", "화", "수", "목", "금", "토", "일"]
    presets = []
    today21 = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if today21 > now:
        presets.append({"label": "오늘 21:00", "value": today21.strftime(fmt)})
    tomorrow = today21 + timedelta(days=1)
    presets.append({"label": f"내일({names[tomorrow.weekday()]}) 21:00", "value": tomorrow.strftime(fmt)})
    sat = today21 + timedelta(days=(5 - today21.weekday()) % 7)
    if sat <= now:
        sat += timedelta(days=7)
    if sat.date() not in (today21.date(), tomorrow.date()):
        presets.append({"label": "토 21:00", "value": sat.strftime(fmt)})
    return presets
