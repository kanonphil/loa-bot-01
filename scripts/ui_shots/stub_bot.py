"""스크린샷용 봇 내부 API 스텁 — webapp이 부르는 /api/internal/* 를 그럴듯한 데이터로 응답."""
import sys
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, r"C:\Users\xoghk\Desktop\loa-bot-01")
import os
os.environ.setdefault("DISCORD_CLIENT_ID", "x"); os.environ.setdefault("DISCORD_CLIENT_SECRET", "x")
os.environ.setdefault("BOT_API_WEBAPP_KEY", "k"); os.environ.setdefault("DISCORD_GUILD_ID", "1"); os.environ.setdefault("SESSION_SECRET", "s")
from webapp.tests.test_character_detail_route import DETAIL  # noqa: E402

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)
ME = "111"
app = FastAPI()

CHARS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1735.0, "account_label": "본계정", "cached_at": (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")},
    {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1722.5, "account_label": "본계정", "cached_at": (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")},
    {"character_name": "소서리스", "character_class": "소서리스", "item_level": 1700.0, "account_label": "본계정", "cached_at": (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")},
]
RAIDS = {
    "아르모체(4막)": {"short_name": "4막", "icon": "🗡️", "category": "카제로스", "is_extreme": False, "is_active": True, "is_pinned": True, "sort_order": 0,
                  "available_from": None, "available_until": None,
                  "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2, "sort_order": 0}, "하드": {"min_level": 1720, "total_slots": 8, "party_split": 4, "gates": 2, "sort_order": 1}}},
    "종막": {"short_name": "종막", "icon": "⚔️", "category": "카제로스", "is_extreme": False, "is_active": True, "is_pinned": False, "sort_order": 1,
            "available_from": None, "available_until": None,
            "difficulties": {"노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2, "sort_order": 0}, "하드": {"min_level": 1730, "total_slots": 8, "party_split": 4, "gates": 2, "sort_order": 1}}},
    "세르카": {"short_name": "세르카", "icon": "🌊", "category": "카제로스", "is_extreme": False, "is_active": True, "is_pinned": False, "sort_order": 2,
             "available_from": None, "available_until": None,
             "difficulties": {"노말": {"min_level": 1700, "total_slots": 4, "party_split": None, "gates": 2, "sort_order": 0}, "하드": {"min_level": 1730, "total_slots": 4, "party_split": None, "gates": 2, "sort_order": 1}}},
    "카멘 익스트림": {"short_name": "익스", "icon": "🔥", "category": "익스트림", "is_extreme": True, "is_active": True, "is_pinned": False, "sort_order": 0,
                 "available_from": (now - timedelta(days=2)).isoformat(), "available_until": (now + timedelta(days=12)).isoformat(),
                 "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 1, "sort_order": 0}, "하드": {"min_level": 1730, "total_slots": 8, "party_split": 4, "gates": 1, "sort_order": 1}}},
}
CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}, {"name": "익스트림", "sort_order": 1, "is_extreme": 1}]

def party(mid, raid, diff, leader, start, status="recruiting", slots=None, memo=None):
    return {"message_id": mid, "channel_id": "c" + mid, "guild_id": "1", "leader_id": leader, "raid_name": raid, "difficulty": diff,
            "proficiency": "숙련", "scheduled_time": start.strftime("%m/%d %H:%M"), "scheduled_datetime": start.isoformat(),
            "total_slots": RAIDS[raid]["difficulties"][diff]["total_slots"], "min_level": RAIDS[raid]["difficulties"][diff]["min_level"],
            "status": status, "memo": memo, "slots": slots or [], "comment_count": 2, "waitlist_count": 1, "created_at": now.isoformat()}

def slot(n, did, name, cls, role): return {"slot_number": n, "discord_id": did, "character_name": name, "character_class": cls, "role": role, "is_guest": False}

PARTIES = [
    party("p1", "아르모체(4막)", "하드", ME, now + timedelta(hours=3), slots=[slot(1, ME, "발키리", "홀리나이트", "support"), slot(2, "222", "리퍼짱", "리퍼", "dps"), slot(3, "333", "버서커", "버서커", "dps")], memo="음성 필수 · 9시 정각 출발"),
    party("p2", "종막", "노말", "222", now + timedelta(days=1, hours=2), slots=[slot(1, "222", "리퍼짱", "리퍼", "dps"), slot(2, "444", "바드님", "바드", "support"), slot(3, "555", "건슬", "건슬링어", "dps"), slot(4, "666", "데헌", "데빌헌터", "dps"), slot(5, "777", "블레", "블레이드", "dps")]),
    party("p3", "카멘 익스트림", "노말", "888", now + timedelta(days=2), slots=[slot(1, "888", "스카", "스카우터", "dps")]),
    party("p4", "세르카", "하드", ME, now - timedelta(hours=5), status="full", slots=[slot(1, ME, "워로드부캐", "워로드", "dps"), slot(2, "222", "리퍼짱", "리퍼", "dps"), slot(3, "444", "바드님", "바드", "support"), slot(4, "555", "건슬", "건슬링어", "dps")]),
]
COMMENTS = [
    {"id": 1, "discord_id": "222", "author_name": "리퍼짱", "content": "9시에 정확히 출발하나요?", "source": "discord", "created_at": now.strftime("%Y-%m-%d %H:%M")},
    {"id": 2, "discord_id": ME, "author_name": "발키리", "content": "네, 5분 전에 모여주세요.", "source": "web", "created_at": now.strftime("%Y-%m-%d %H:%M")},
]
INVITES = [{"message_id": "p2", "slot_number": 6, "invited_at": (datetime.utcnow() - timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%S"),
            "raid_name": "종막", "difficulty": "노말", "proficiency": "숙련", "scheduled_time": PARTIES[1]["scheduled_time"],
            "scheduled_datetime": PARTIES[1]["scheduled_datetime"], "leader_id": "222", "min_level": 1710, "status": "recruiting"}]

def j(x): return JSONResponse(x)

@app.get("/api/internal/verify-user")
async def verify(discord_id: str): return j({"discord_id": discord_id, "registered": True})
@app.get("/api/internal/guild-info")
async def guild(): return j({"name": "동물롱장", "icon_url": None})
@app.get("/api/internal/user-characters")
async def uc(discord_id: str): return j([{k: v for k, v in c.items() if k != "account_label"} for c in CHARS])
@app.get("/api/internal/user-characters-grouped")
async def ucg(discord_id: str): return j(CHARS)
@app.get("/api/internal/accounts/list")
async def accounts(discord_id: str): return j([{"id": 1, "label": "본계정", "added_at": now.isoformat(), "masked_key": "eyJ0eXAi****9fQ"}])
@app.get("/api/internal/raids")
async def raids(): return j(RAIDS)
@app.get("/api/internal/raid-categories")
async def cats(): return j(CATEGORIES)
@app.get("/api/internal/support-classes")
async def sup(): return j(["홀리나이트", "바드", "도화가", "발키리"])
@app.get("/api/internal/parties/proficiency-options")
async def prof(): return j([{"value": "트라이", "label": "트라이", "description": "처음 도전"}, {"value": "반숙", "label": "반숙", "description": ""}, {"value": "숙련", "label": "숙련", "description": "완전 숙지"}])
@app.get("/api/internal/parties")
async def parties(guild_id: str): return j(PARTIES)
@app.get("/api/internal/parties/calendar")
async def cal(): return j(PARTIES)
@app.get("/api/internal/parties/{mid}")
async def pdetail(mid: str):
    p = next((p for p in PARTIES if p["message_id"] == mid), None)
    return j(p)
@app.get("/api/internal/parties/{mid}/comments")
async def comments(mid: str): return j(COMMENTS)
@app.get("/api/internal/parties/{mid}/eligibility")
async def elig(mid: str, discord_id: str):
    return j({"can_join": True, "qualifying": [{"name": "워로드부캐", "class": "워로드", "level": 1722.5}, {"name": "발키리", "class": "홀리나이트", "level": 1735.0}],
              "party_split": 4, "total_slots": 8, "gold_done": [], "in_other_party": [], "level_too_low": [], "no_cache": [], "min_level": 1710})
@app.get("/api/internal/parties/{mid}/waitlist-status")
async def wl(mid: str, discord_id: str): return j({"on_waitlist": False, "count": 1})
@app.get("/api/internal/parties/{mid}/invitable-users")
async def inv_users(mid: str, discord_id: str): return j({"success": True, "users": [{"discord_id": "999", "representative": "기공사님"}, {"discord_id": "998", "representative": "창술사님"}], "available_slots": [4, 5, 6, 7, 8]})
@app.get("/api/internal/parties/{mid}/switch-eligibility")
async def sw(mid: str, discord_id: str): return j({"can_switch": True, "current_character": "발키리", "candidates": [{"name": "워로드부캐", "level": 1722.5, "class": "워로드", "in_other_party": None}], "gold_done": [], "level_too_low": [], "no_cache": []})
@app.get("/api/internal/completions")
async def comp(discord_id: str, character_name: str): return j({"week_key": "w", "completions": ["아르모체(4막)_하드"] if character_name == "발키리" else []})
@app.get("/api/internal/completions/extreme")
async def ext(discord_id: str): return j({"week_key": "w", "raids": [{"raid_name": "카멘 익스트림", "short_name": "익스", "icon": "🔥", "cleared": False, "character_name": None, "difficulty": None, "difficulties": RAIDS["카멘 익스트림"]["difficulties"], "available_from": RAIDS["카멘 익스트림"]["available_from"], "available_until": RAIDS["카멘 익스트림"]["available_until"]}]})
@app.get("/api/internal/completions/weeks")
async def weeks(discord_id: str): return j({"current_week": "2026-09-23", "weeks": ["2026-09-23", "2026-09-16"]})
@app.get("/api/internal/completions/week")
async def week(discord_id: str, week_key: str): return j({"week_key": week_key, "characters": [{"character_name": "발키리", "character_class": "홀리나이트", "completions": [{"raid_name": "아르모체(4막)", "difficulty": "하드"}, {"raid_name": "종막", "difficulty": "노말"}]}]})
@app.get("/api/internal/raid-selection")
async def sel(discord_id: str, character_name: str): return j({"customized": False, "selected_raids": []})
@app.get("/api/internal/raid-progress")
async def prog(discord_id: str):
    return j({"week_key": "w", "done": 3, "total": 8, "characters": [
        {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1735.0, "done_count": 2, "total_slots": 3, "remaining": 1},
        {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1722.5, "done_count": 1, "total_slots": 3, "remaining": 2},
        {"character_name": "소서리스", "character_class": "소서리스", "item_level": 1700.0, "done_count": 0, "total_slots": 2, "remaining": 2}],
        "extreme": [{"raid_name": "카멘 익스트림", "short_name": "익스", "cleared": True, "character_name": "발키리", "difficulty": "하드"}]})
@app.get("/api/internal/my-invites")
async def myinv(discord_id: str): return j(INVITES)
@app.get("/api/internal/user-party-history")
async def hist(discord_id: str, limit: int = 20, offset: int = 0):
    return j({"entries": [{"message_id": "h1", "raid_name": "종막", "difficulty": "하드", "proficiency": "숙련", "scheduled_time": "09/20 21:00", "status": "disbanded", "character_name": "발키리", "role": "support", "created_at": now.isoformat(), "total_slots": 8, "memo": None, "leader_id": "222",
                          "members": [{"discord_id": "222", "character_name": "리퍼짱", "character_class": "리퍼", "role": "dps"}, {"discord_id": ME, "character_name": "발키리", "character_class": "홀리나이트", "role": "support"}]}], "has_more": False, "total_count": 1})
@app.get("/api/internal/ranking")
async def rank(metric: str = "combat_power", role: str = "dps", limit: int = 100):
    return j({"metric": metric, "role": role, "entries": [
        {"discord_id": ME, "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1735.0, "combat_power": 4300000, "value": 4300000, "rank": 1},
        {"discord_id": "222", "character_name": "리퍼짱", "character_class": "리퍼", "item_level": 1730.0, "combat_power": 4100000, "value": 4100000, "rank": 2},
        {"discord_id": "444", "character_name": "바드님", "character_class": "바드", "item_level": 1720.0, "combat_power": 3900000, "value": 3900000, "rank": 3},
        {"discord_id": "555", "character_name": "건슬", "character_class": "건슬링어", "item_level": 1712.0, "combat_power": 3700000, "value": 3700000, "rank": 4}]})
@app.get("/api/internal/armory-detail")
async def armory(discord_id: str, character_name: str): return j({**DETAIL, "synced_at": (datetime.utcnow() - timedelta(hours=2)).isoformat()})
@app.get("/api/internal/subscriptions")
async def subs(discord_id: str): return j([{"raid_name": "종막", "difficulty": "전체", "created_at": now.isoformat()}])
@app.get("/api/internal/preferences")
async def prefs(discord_id: str): return j({"pre_notify_hours": 1.0, "choices": [0.0, 0.5, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0]})
@app.get("/api/internal/web-notifications")
async def webn(): return j({"latest_id": 0, "items": []})
@app.get("/api/internal/admin/parties")
async def adm_parties(): return j({"open": PARTIES[:3], "closed": [{**PARTIES[3], "status": "disbanded", "is_live": True}]})
@app.get("/api/internal/admin/status")
async def adm_status(): return j({"is_online": True, "uptime_str": "3일 4시간", "user_count": 22, "active_party_count": 3, "subscription_count": 10, "latency_ms": 41.2})
@app.get("/api/internal/admin/forum-channel")
async def adm_forum(): return j({"forum_channel_id": "700", "forum_channel_name": "공대모집", "channels": [{"id": "700", "name": "공대모집"}]})
@app.get("/api/internal/admin/users")
async def adm_users(): return j([{"discord_id": ME, "representative": "발키리", "character_count": 3, "registered_at": now.isoformat(), "last_sync": now.isoformat(), "is_admin": True}])
@app.get("/api/internal/admin/raids/references")
async def adm_refs(): return j({"parties_live": 1, "parties_all": 2, "party_history": 12, "raid_completions": 88, "raid_subscriptions": 3, "character_raid_selection": 5, "notification_logs": 4})
@app.get("/api/internal/job-classes")
async def jobs(): return j([{"name": "홀리나이트", "is_support": 1}, {"name": "워로드", "is_support": 0}, {"name": "바드", "is_support": 1}, {"name": "리퍼", "is_support": 0}])

@app.api_route("/api/internal/{rest:path}", methods=["GET", "POST"])
async def catch_all(rest: str, request: Request):
    return j({"success": True} if request.method == "POST" else {})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
