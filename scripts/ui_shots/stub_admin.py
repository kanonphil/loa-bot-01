"""관리 화면 스크린샷용 스텁 — stub_bot.py가 한 줄로 불러온다(`import stub_admin; stub_admin.register(app, globals())`).

기존 /admin/* 응답을 같은 경로로 덮어쓰고(관리 화면에 맞게 더 풍부하게), 2단계 계약에 새로 생긴
엔드포인트(작업 기록·영향 범위·시세 아이템·공지 진행 상황)를 더한다. STUB_ADMIN_MISSING=1이면 새 엔드포인트를
404로 둬서 "봇이 아직 모를 때" 화면을 확인할 수 있다."""
import os
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse

KST = timezone(timedelta(hours=9))


def register(app, g):
    now = datetime.now(KST)
    PARTIES, RAIDS, ME = g["PARTIES"], g["RAIDS"], g["ME"]
    party, slot = g["party"], g["slot"]
    missing_new = os.environ.get("STUB_ADMIN_MISSING") == "1"

    # 클리어 골드(계약 §2) — 일부만 채워 "미입력" 표시도 보이게
    for name, gold in (("종막", {"노말": 1500, "하드": 2300}), ("아르모체(4막)", {"노말": 1000})):
        for diff, v in gold.items():
            RAIDS[name]["difficulties"][diff]["clear_gold"] = v

    def drop(path, method):
        app.router.routes[:] = [
            r for r in app.router.routes
            if not (getattr(r, "path", None) == path and method in getattr(r, "methods", set()))
        ]

    def get(path, fn):
        drop(path, "GET")
        app.get(path)(fn)

    def post(path, fn):
        drop(path, "POST")
        app.post(path)(fn)

    def j(x, status=200):
        return JSONResponse(x, status_code=status)

    # ── 공대 ──
    open_parties = [
        party("p1", "아르모체(4막)", "하드", ME, now + timedelta(hours=3), slots=[slot(1, ME, "발키리", "홀리나이트", "support"), slot(2, "222", "리퍼짱", "리퍼", "dps"), slot(3, "333", "버서커", "버서커", "dps")]),
        party("p2", "종막", "노말", "222", now + timedelta(days=1, hours=2), slots=[slot(1, "222", "리퍼짱", "리퍼", "dps"), slot(2, "444", "바드님", "바드", "support"), slot(3, "555", "건슬", "건슬링어", "dps"), slot(4, "666", "데헌", "데빌헌터", "dps"), slot(5, "777", "블레", "블레이드", "dps")]),
        party("p3", "카멘 익스트림", "노말", "888", now + timedelta(days=2), slots=[slot(1, "888", "스카", "스카우터", "dps")]),
        party("p4", "세르카", "하드", ME, now - timedelta(hours=5), status="full", slots=[slot(1, ME, "워로드부캐", "워로드", "dps"), slot(2, "222", "리퍼짱", "리퍼", "dps"), slot(3, "444", "바드님", "바드", "support"), slot(4, "555", "건슬", "건슬링어", "dps")]),
        party("p5", "종막", "하드", "444", now + timedelta(days=3), status="closed", slots=[slot(1, "444", "바드님", "바드", "support")]),
    ]
    closed = [
        {**party("c1", "세르카", "노말", "222", now - timedelta(days=1), status="disbanded", slots=[slot(1, "222", "리퍼짱", "리퍼", "dps"), slot(2, "333", "버서커", "버서커", "dps")]),
         "is_live": True, "can_revert": True, "cleared_at": now.isoformat()},
        {**party("c2", "종막", "하드", "222", now - timedelta(days=2), status="expired", slots=[slot(1, "222", "리퍼짱", "리퍼", "dps")]),
         "is_live": True, "can_revert": False},
        {**party("c3", "아르모체(4막)", "노말", "333", now - timedelta(days=9), status="disbanded", slots=[]), "is_live": False, "can_revert": False},
    ]
    get("/api/internal/admin/parties", lambda: j({"open": open_parties, "closed": closed}))

    # ── 유저 ──
    stale = (datetime.utcnow() - timedelta(days=42)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    active = (datetime.utcnow() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    users = [
        {"discord_id": ME, "representative": "발키리", "discord_nick": "valkyrie", "character_count": 3, "registered_at": now.isoformat(), "last_sync": fresh, "last_active_at": active},
        {"discord_id": "222", "representative": "리퍼짱", "discord_nick": "ripper", "character_count": 6, "registered_at": now.isoformat(), "last_sync": fresh, "last_active_at": fresh},
        {"discord_id": "333", "representative": "버서커", "discord_nick": "berserk", "character_count": 3, "registered_at": now.isoformat(), "last_sync": stale, "last_active_at": stale},
        {"discord_id": "444", "representative": "바드님", "discord_nick": "bard", "character_count": 4, "registered_at": now.isoformat(), "last_sync": fresh, "last_active_at": None},
        {"discord_id": "999", "representative": None, "discord_nick": None, "character_count": 0, "registered_at": now.isoformat(), "last_sync": None, "last_active_at": None},
    ]
    get("/api/internal/admin/users", lambda: j(users))
    get("/api/internal/admin/users/{uid}/characters", lambda uid: j([
        {"character_name": "버서커", "character_class": "버서커", "item_level": 1715.0}, {"character_name": "버서커부캐", "character_class": "워로드", "item_level": 1700.0}]))
    get("/api/internal/admin/users/{uid}/history", lambda uid: j({"entries": [
        {"message_id": "h1", "raid_name": "종막", "difficulty": "하드", "proficiency": "숙련", "scheduled_time": "09/20 21:00", "status": "disbanded", "character_name": "버서커", "role": "dps", "created_at": now.isoformat(), "total_slots": 8}], "has_more": False, "total_count": 1}))

    async def impact(uid: str):
        if missing_new:
            return j({"detail": "not found"}, 404)
        return j({"characters": 3, "api_keys": 1, "completions_this_week": 4, "active_parties": [
            {"message_id": "p2", "raid_name": "종막", "difficulty": "노말", "is_leader": True, "handover_to": {"discord_id": "444", "name": "바드님"}},
            {"message_id": "p1", "raid_name": "아르모체(4막)", "difficulty": "하드", "is_leader": False, "handover_to": None}]})
    get("/api/internal/admin/users/{uid}/impact", impact)

    # ── 작업 기록 ──
    def ago(**kw):
        return (now - timedelta(**kw)).isoformat()
    actions = [
        {"id": 5, "at": ago(minutes=13), "actor_name": "발키리", "source": "web", "action": "party.force_close", "summary": "종막 노말 공대 강제 마감", "undoable": True, "undone_at": None},
        {"id": 4, "at": ago(days=1, hours=2), "actor_name": "발키리", "source": "web", "action": "raid.rename", "summary": "레이드 이름 \"카멘(익스)\" → \"카멘 익스트림\" · 공대 1, 기록 34건 함께 변경", "undoable": True, "undone_at": None},
        {"id": 3, "at": ago(days=3), "actor_name": "리퍼짱", "source": "discord", "action": "party.revert_clear", "summary": "세르카 하드 클리어 되돌리기 · 참여자 4명 체크 해제", "undoable": False, "undone_at": None},
        {"id": 2, "at": ago(days=4), "actor_name": "발키리", "source": "web", "action": "notify_all", "summary": "전체 DM 발송 · 22명 중 21명 전송, 1명 DM 차단", "undoable": False, "undone_at": None},
        {"id": 1, "at": ago(days=5), "actor_name": "발키리", "source": "web", "action": "raid.disable", "summary": "레이드 \"카멘 익스트림\" 비활성화", "undoable": True, "undone_at": ago(days=5, hours=-1)},
    ]

    async def actions_list(kind: str = "all", limit: int = 100):
        if missing_new:
            return j({"detail": "not found"}, 404)
        keep = {"party": "party", "raid": "raid", "user": "user"}.get(kind)
        return j({"items": [a for a in actions if not keep or a["action"].startswith(keep)]})
    get("/api/internal/admin/actions", actions_list)

    # ── 시세 아이템 / 공지 진행 ──
    async def tracked_get():
        if missing_new:
            return j({"detail": "not found"}, 404)
        return j({"names": ["운명의 파괴석 결정", "운명의 수호석 결정", "위대한 운명의 돌파석"]})
    get("/api/internal/admin/loa/tracked-items", tracked_get)
    post("/api/internal/admin/loa/tracked-items", lambda: j({"success": True, "names": [], "unresolved": []}))
    sent = {"n": None}

    async def notify_all():
        sent["n"] = 0
        return j({"success": True, "queued": True, "total": 22})

    async def notify_status():
        if sent["n"] is None:
            return j({})
        sent["n"] = min(22, sent["n"] + 8)
        return j({"sent": sent["n"], "total": 22, "done": sent["n"] >= 22})
    post("/api/internal/admin/notify-all", notify_all)
    get("/api/internal/admin/notify-all/status", notify_status)

    # ── 통계 · 알림 ──
    get("/api/internal/admin/stats/weeks", lambda: j({"current": "2026-09-23", "weeks": ["2026-09-23", "2026-09-16", "2026-09-09"]}))
    get("/api/internal/admin/stats/weekly", lambda: j({"week_key": "2026-09-23", "data": [
        {"raid_name": "종막", "difficulty": "하드", "count": 12}, {"raid_name": "종막", "difficulty": "노말", "count": 9}, {"raid_name": "아르모체(4막)", "difficulty": "하드", "count": 7}]}))
    get("/api/internal/admin/stats/characters", lambda: j({"week_key": "2026-09-23", "data": [
        {"discord_id": "222", "representative": "리퍼짱", "character_name": "리퍼짱", "clears": 6}, {"discord_id": ME, "representative": "발키리", "character_name": "발키리", "clears": 5}]}))
    get("/api/internal/admin/stats/activity", lambda: j({"active_users": {"user_count": 18}, "weekly_parties": [
        {"week": "2026-09-09", "count": 11}, {"week": "2026-09-16", "count": 14}, {"week": "2026-09-23", "count": 9}], "popular_raids": [
        {"raid_name": "종막", "difficulty": "하드", "count": 41}, {"raid_name": "아르모체(4막)", "difficulty": "노말", "count": 33}]}))
    get("/api/internal/admin/subscriptions", lambda: j([
        {"raid_name": "종막", "difficulty": "하드", "discord_id": "222", "representative": "리퍼짱"},
        {"raid_name": "종막", "difficulty": "하드", "discord_id": "444", "representative": "바드님"},
        {"raid_name": "세르카", "difficulty": None, "discord_id": ME, "representative": "발키리"}]))
    get("/api/internal/admin/notification-logs", lambda: j([
        {"sent_at": (datetime.utcnow() - timedelta(minutes=30)).isoformat(), "discord_id": "222", "raid_name": "종막", "difficulty": "하드", "message_id": "p2"},
        {"sent_at": (datetime.utcnow() - timedelta(hours=5)).isoformat(), "discord_id": "444", "raid_name": "세르카", "difficulty": "노말", "message_id": "p4"}]))
    get("/api/internal/admin/completions", lambda: j({"week_key": "2026-09-23", "completions": ["종막_노말", "아르모체(4막)_하드"]}))
