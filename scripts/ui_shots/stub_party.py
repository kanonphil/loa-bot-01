"""공대 화면용 스텁 데이터 — stub_bot.py가 한 줄로 불러 쓴다(install(globals())).
모집중·마감·파티완성·기한 만료·클리어·관리자 종료, 분할 공대, 인원이 많은 공대, 서포터 없는 공대를 섞어 둔다."""
from datetime import datetime, timedelta

from fastapi.responses import JSONResponse

REPLACED = ("/api/internal/parties", "/api/internal/parties/{mid}", "/api/internal/parties/calendar", "/api/internal/user-party-history")


def install(ns: dict) -> None:
    app, party, slot, now, ME, RAIDS, CHARS = ns["app"], ns["party"], ns["slot"], ns["now"], ns["ME"], ns["RAIDS"], ns["CHARS"]
    PARTIES = ns["PARTIES"]
    j = lambda x: JSONResponse(x)  # noqa: E731

    p1, p2, p3, p4 = PARTIES[0], PARTIES[1], PARTIES[2], PARTIES[3]
    p5 = party("p5", "종막", "하드", "444", now + timedelta(days=1, hours=5), status="closed", memo="클경 · 마감했어요", slots=[
        slot(1, "444", "바드님", "바드", "support"), slot(2, "222", "리퍼짱", "리퍼", "dps"), slot(3, "555", "건슬", "건슬링어", "dps"),
        slot(4, "666", "데헌", "데빌헌터", "dps"), slot(5, "777", "블레", "블레이드", "dps"), slot(6, "888", "스카", "스카우터", "dps")])
    p6 = party("p6", "아르모체(4막)", "노말", "555", now + timedelta(hours=30), memo="초행 환영 · 음성 필수 · 9시 정각 출발해요", slots=[
        slot(1, "555", "건슬", "건슬링어", "dps"), slot(2, "666", "데헌", "데빌헌터", "dps"), slot(3, "777", "블레", "블레이드", "dps"),
        slot(4, "222", "리퍼짱", "리퍼", "dps"), slot(5, ME, "워로드부캐", "워로드", "dps"), slot(6, "888", "스카", "스카우터", "dps"),
        slot(7, "999", "도화가님", "도화가", "support")])
    p7 = party("p7", "종막", "노말", "222", now - timedelta(days=2), status="expired", slots=[
        slot(1, "222", "리퍼짱", "리퍼", "dps"), slot(2, ME, "발키리", "홀리나이트", "support")])
    p8 = party("p8", "세르카", "노말", "222", now - timedelta(days=1), status="disbanded", slots=[
        slot(1, "222", "리퍼짱", "리퍼", "dps"), slot(2, ME, "발키리", "홀리나이트", "support"), slot(3, "555", "건슬", "건슬링어", "dps"), slot(4, "666", "데헌", "데빌헌터", "dps")])
    p8["cleared_at"] = (now - timedelta(days=1, hours=-1)).isoformat()
    p9 = party("p9", "아르모체(4막)", "하드", "222", now - timedelta(days=1), status="disbanded", slots=[slot(1, "222", "리퍼짱", "리퍼", "dps")])
    p9["cleared_at"] = None
    p7["ended_at"] = (now - timedelta(days=1)).isoformat()
    p7["cleared_at"] = None
    for p in (p1, p2, p3, p4, p5, p6):
        p.setdefault("cleared_at", None)
    p6["created_at"] = (now - timedelta(days=1)).isoformat()
    PARTIES[:] = [p1, p2, p3, p4, p5, p6]
    ENDED = [p7, p8, p9]
    ALL = PARTIES + ENDED

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") not in REPLACED]

    @app.get("/api/internal/parties")
    async def parties_active(guild_id: str):
        return j(PARTIES)

    @app.get("/api/internal/parties/calendar")
    async def parties_calendar():
        return j(ALL)

    @app.get("/api/internal/parties/{mid}")
    async def party_detail(mid: str):
        return j(next((p for p in ALL if p["message_id"] == mid), None))

    @app.post("/api/internal/parties/create")
    async def create():
        return j({"success": True, "message_id": "p1"})

    sup = {"홀리나이트", "바드", "도화가", "발키리"}

    @app.get("/api/internal/raid-check-summary")
    async def summary(discord_id: str):
        done = {"발키리": ["아르모체(4막)_하드"], "워로드부캐": ["종막_노말"], "소서리스": []}
        return j({
            "week_key": "w", "raids": RAIDS, "categories": [], "support_classes": sorted(sup),
            "extreme": [{"raid_name": "카멘 익스트림", "short_name": "익스", "icon": None, "cleared": False, "character_name": None, "difficulty": None,
                         "available_from": RAIDS["카멘 익스트림"]["available_from"], "available_until": RAIDS["카멘 익스트림"]["available_until"],
                         "difficulties": RAIDS["카멘 익스트림"]["difficulties"]}],
            "characters": [{**{k: v for k, v in c.items() if k != "account_label"}, "is_support": c["character_class"] in sup,
                            "completions": done.get(c["character_name"], []), "selection": {"customized": False, "selected_raids": []},
                            "applicable_raids": [], "visible_raid_names": [], "done_count": 0, "total_slots": 0} for c in CHARS],
        })

    @app.get("/api/internal/user-party-history")
    async def history(discord_id: str, limit: int = 20, offset: int = 0):
        def e(mid, raid, diff, when, status, prof="숙련", memo=None):
            return {"message_id": mid, "raid_name": raid, "difficulty": diff, "proficiency": prof, "scheduled_time": when, "status": status,
                    "character_name": "발키리", "role": "support", "created_at": now.isoformat(), "total_slots": 8, "memo": memo, "leader_id": ME,
                    "members": [{"discord_id": "222", "character_name": "리퍼짱", "character_class": "리퍼", "role": "dps"},
                                {"discord_id": ME, "character_name": "발키리", "character_class": "홀리나이트", "role": "support"}]}
        entries = [e("h1", "아르모체(4막)", "하드", "11/13 21:00", "disbanded", memo="음성 필수"), e("h2", "종막", "노말", "11/15 22:00", "expired", "반숙"),
                   e("h3", "세르카", "하드", "11/09 20:00", "disbanded"), e("h4", "종막", "하드", "11/07 21:00", "cancelled", "트라이")]
        return j({"entries": entries, "has_more": False, "total_count": len(entries)})
