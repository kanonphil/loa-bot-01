"""홈 화면용 스텁 엔드포인트 — 숙제 체크가 실제로 상태를 바꾸도록 메모리에 들고 있는다.
stub_bot.py가 RAIDS·CHARS 정의 직후 register(app, RAIDS, CHARS)로 불러온다(먼저 등록돼야 같은 경로의 정적 스텁을 덮는다)."""
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse

KST = timezone(timedelta(hours=9))
GOLD = {"아르모체(4막)": {"노말": 10000, "하드": 14000}, "종막": {"노말": 9500, "하드": 13000}, "세르카": {"노말": 8000, "하드": 11000},
        "카멘 익스트림": {"노말": 20000, "하드": 30000}}


def register(app, RAIDS, CHARS):
    now = datetime.now(KST)
    done = {"발키리": {"아르모체(4막)_하드"}, "워로드부캐": {"종막_노말"}, "소서리스": set()}
    ext = {"cleared": None}
    sub = {"on": False}

    def applicable(level):
        out = []
        for name, info in RAIDS.items():
            if info["is_extreme"]:
                continue
            diffs = [d for d, v in info["difficulties"].items() if level >= v["min_level"]]
            if diffs:
                out.append({"raid_name": name, "short_name": info["short_name"], "icon": info["icon"], "category": info["category"],
                            "difficulties": diffs, "difficulty_gold": {d: GOLD[name][d] for d in diffs}})
        return out

    def char_row(c):
        app_raids = applicable(c["item_level"])
        mine = done[c["character_name"]]
        done_raids = {k.rsplit("_", 1)[0] for k in mine}
        earned = sum(GOLD[k.rsplit("_", 1)[0]][k.rsplit("_", 1)[1]] for k in mine)
        total = earned
        for r in app_raids:
            if r["raid_name"] not in done_raids:
                total += max(r["difficulty_gold"].values())
        return {**c, "is_support": False, "completions": sorted(mine), "selection": {"customized": False, "selected_raids": []},
                "applicable_raids": app_raids, "visible_raid_names": [r["raid_name"] for r in app_raids],
                "done_count": len(done_raids), "total_slots": len(app_raids), "gold_earned": earned, "gold_total": total}

    def extreme_payload():
        info = RAIDS["카멘 익스트림"]
        c = ext["cleared"]
        return [{"raid_name": "카멘 익스트림", "short_name": "익스", "icon": info["icon"], "available_from": info["available_from"],
                 "available_until": info["available_until"], "difficulties": info["difficulties"],
                 "cleared": c is not None, "character_name": c[0] if c else None, "difficulty": c[1] if c else None}]

    @app.get("/api/internal/raid-check-summary")
    async def summary(discord_id: str):
        rows = [char_row(c) for c in CHARS]
        return JSONResponse({"week_key": "w", "characters": rows, "raids": RAIDS, "categories": [], "support_classes": [],
                             "extreme": extreme_payload(),
                             "gold": {"earned": sum(r["gold_earned"] for r in rows), "total": sum(r["gold_total"] for r in rows)}})

    @app.get("/api/internal/completions")
    async def completions(discord_id: str, character_name: str):
        return JSONResponse({"week_key": "w", "completions": sorted(done.get(character_name, set()))})

    @app.post("/api/internal/completions/toggle")
    async def toggle(request: Request):
        b = await request.json()
        key = f"{b['raid_name']}_{b['difficulty']}"
        mine = done[b["character_name"]]
        if key in mine:
            mine.discard(key)
            return JSONResponse({"success": True, "completed": False})
        for k in [k for k in mine if k.rsplit("_", 1)[0] == b["raid_name"]]:
            mine.discard(k)
        mine.add(key)
        return JSONResponse({"success": True, "completed": True})

    @app.get("/api/internal/completions/extreme")
    async def extreme_status(discord_id: str):
        return JSONResponse({"week_key": "w", "raids": extreme_payload()})

    @app.post("/api/internal/completions/extreme/set")
    async def extreme_set(request: Request):
        b = await request.json()
        ext["cleared"] = (b["character_name"], b["difficulty"])
        return JSONResponse({"success": True})

    @app.post("/api/internal/completions/extreme/clear")
    async def extreme_clear(request: Request):
        ext["cleared"] = None
        return JSONResponse({"success": True})

    @app.get("/api/internal/loa/overview")
    async def overview(discord_id: str):
        def at(h, m=0):
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return (t if t > now else t + timedelta(days=1)).isoformat()
        return JSONResponse({
            "available": True, "reason": None, "fetched_at": now.isoformat(),
            "maintenance": {"active": True, "title": f"{now.month}월 {now.day}일 정기 점검 안내", "starts_at": now.replace(hour=6, minute=0).isoformat(),
                            "ends_at": now.replace(hour=10, minute=0).isoformat(), "link": "https://example.com/notice"},
            "notices": [],
            "events": [{"title": "이벤트 A", "thumbnail": "", "link": "https://example.com/a", "start": now.isoformat(), "end": (now + timedelta(days=3)).isoformat()},
                       {"title": "이벤트 B", "thumbnail": "", "link": "https://example.com/b", "start": now.isoformat(), "end": (now + timedelta(days=12)).isoformat()},
                       {"title": "이벤트 C", "thumbnail": "", "link": "", "start": now.isoformat(), "end": (now + timedelta(days=20)).isoformat()}],
            "today": [{"category": "모험 섬", "name": "모험섬 A", "icon": "", "min_item_level": 0, "times": [at(19)], "is_gold": True, "rewards": [{"name": "골드"}, {"name": "실링"}]},
                      {"category": "모험 섬", "name": "모험섬 B", "icon": "", "min_item_level": 0, "times": [at(19)], "is_gold": False, "rewards": [{"name": "카드 팩"}, {"name": "해적 주화"}]},
                      {"category": "모험 섬", "name": "모험섬 C", "icon": "", "min_item_level": 0, "times": [at(19)], "is_gold": False, "rewards": [{"name": "실링"}, {"name": "주화"}]},
                      {"category": "필드보스", "name": "필드보스 A", "icon": "", "min_item_level": 0, "times": [at(20)], "is_gold": False, "rewards": []},
                      {"category": "카오스게이트", "name": "카오스게이트", "icon": "", "min_item_level": 0, "times": [at(21)], "is_gold": False, "rewards": []}],
            "gold_island_subscribed": sub["on"]})

    @app.get("/api/internal/loa/prices")
    async def prices():
        def hist(vals):
            return [{"date": f"2026-11-{10 + i}", "avg": v} for i, v in enumerate(vals)]
        return JSONResponse({"available": True, "fetched_at": now.isoformat(), "items": [
            {"id": 1, "name": "재련 재료 A", "icon": "", "current": 105, "yday_avg": 92, "change_pct": 13.6, "history": hist([95, 92, 94, 99, 108, 104, 112])},
            {"id": 2, "name": "재련 재료 B", "icon": "", "current": 90, "yday_avg": 99, "change_pct": -9.5, "history": hist([110, 104, 118, 100, 94, 90, 90])},
            {"id": 3, "name": "보석 (경매장 최저)", "icon": "", "current": 1500, "yday_avg": 1420, "change_pct": 5.5, "history": hist([1380, 1400, 1450, 1430, 1460, 1480, 1500])}]})

    @app.post("/api/internal/loa/gold-island-subscription")
    async def gold_sub(request: Request):
        b = await request.json()
        sub["on"] = bool(b["enabled"])
        return JSONResponse({"success": True, "enabled": sub["on"]})
