"""원정대·더보기 화면용 스텁 확장 — 새 봇 엔드포인트(골드섬 구독·시세·전투력 기록·7일 성장)와 실패/지연 시나리오.
stub_bot.py가 catch_all보다 앞에서 register(app)을 한 번 부른다(앞에 등록된 경로가 이긴다)."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse

ME = "111"
STATE = {"gold": False, "sync_mode": "ok"}  # sync_mode: ok | pending


def register(app):
    def j(x, status=200):
        return JSONResponse(x, status_code=status)

    @app.get("/api/internal/ranking")
    async def rank(metric: str = "combat_power", role: str | None = None, limit: int = 100):
        base = [
            ("발키리", "홀리나이트", 1735.0, 2812.45, ME, 41.2),
            ("리퍼짱", "리퍼", 1730.0, 2790.10, "222", 12.5),
            ("워로드부캐", "워로드", 1722.5, 2601.00, ME, -8.75),
            ("바드님", "바드", 1720.0, 2540.30, "444", None),
            ("소서리스", "소서리스", 1700.0, 2412.80, ME, 0.0),
            ("건슬", "건슬링어", 1712.0, 2398.00, "555", 77.0),
        ]
        entries = []
        for name, cls, il, cp, did, growth in base:
            v = cp if metric == "combat_power" else (il if metric == "item_level" else 3)
            entries.append({"discord_id": did, "character_name": name, "character_class": cls, "item_level": il,
                            "combat_power": cp, "value": v, "cp_growth_7d": growth})
        if role == "support":
            entries = [e for e in entries if e["character_class"] in ("바드", "홀리나이트")]
        return j({"metric": metric, "role": role, "entries": entries[:limit]})

    @app.get("/api/internal/loa/overview")
    async def overview(discord_id: str):
        return j({"available": True, "reason": None, "fetched_at": datetime.now(timezone.utc).isoformat(), "maintenance": None,
                  "notices": [], "events": [], "today": [], "gold_island_subscribed": STATE["gold"]})

    @app.post("/api/internal/loa/gold-island-subscription")
    async def gold_sub(body: dict):
        STATE["gold"] = bool(body.get("enabled"))
        return j({"success": True, "enabled": STATE["gold"]})

    @app.get("/api/internal/loa/prices")
    async def prices():
        return j({"available": True, "fetched_at": (datetime.now(timezone.utc) - timedelta(minutes=14)).isoformat(), "items": [
            {"id": "1", "name": "유물 각인서 · 원한", "icon": "", "current": 143000, "yday_avg": 139000.0, "change_pct": 2.9, "history": []},
            {"id": "2", "name": "4레벨 겁화 보석", "icon": "", "current": 98500, "yday_avg": 101000.0, "change_pct": -2.5, "history": []},
            {"id": "3", "name": "운명의 파편 주머니(대)", "icon": "", "current": 2450, "yday_avg": 2450.0, "change_pct": 0.0, "history": []},
        ]})

    @app.get("/api/internal/characters/{name}/history")
    async def history(name: str, discord_id: str, days: int = 90):
        if name == "소서리스":  # 점 1개 -> 빈 상태 확인용
            return j({"items": [{"date": datetime.now().strftime("%Y-%m-%d"), "combat_power": 2412.8, "item_level": 1700.0}]})
        if name == "워로드부캐":  # 404 -> 빈 상태
            return j({"detail": "not found"}, 404)
        today = datetime.now()
        items = []
        for i in range(60, -1, -1):
            v = 2700 + (60 - i) * 1.9 + (12 if i % 9 == 0 else 0) - (7 if i % 13 == 0 else 0)
            items.append({"date": (today - timedelta(days=i)).strftime("%Y-%m-%d"), "combat_power": round(v, 2), "item_level": 1735.0})
        return j({"items": items})

    @app.post("/api/internal/characters/sync")
    async def sync(body: dict):
        await asyncio.sleep(1.5)
        if STATE["sync_mode"] == "pending":
            return j({"success": True, "pending": True})
        return j({"success": True, "updated": 3, "total": 3})

    @app.post("/api/internal/characters/add")
    async def add_char(body: dict):
        if body.get("character_name") == "없는캐릭터":
            return j({"success": False, "reason": "'없는캐릭터' 캐릭터를 찾을 수 없습니다. 이름을 다시 확인해주세요."})
        return j({"success": True, "character_name": body.get("character_name"), "character_class": "버서커", "item_level": 1700.0})

    @app.post("/api/internal/accounts/add")
    async def add_acc(body: dict):
        if body.get("api_key") == "bad":
            return j({"success": False, "reason": "API 키가 올바르지 않습니다. 키를 다시 확인해주세요."})
        return j({"success": True, "label": "부계정", "added": 2, "total": 2})

    @app.post("/__stub/sync-mode")
    async def set_mode(body: dict):
        STATE["sync_mode"] = body.get("mode", "ok")
        return j({"ok": True})
