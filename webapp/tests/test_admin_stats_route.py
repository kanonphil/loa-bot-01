"""웹 관리자 통계/알림·구독/클리어 관리 페이지 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal/admin"
WEEKS = {"current": "2026-09-16", "weeks": ["2026-09-16", "2026-09-09"]}


def _admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    log_in(client, discord_id="111")


def _mock_clears():
    respx.get(f"{B}/stats/weeks").mock(return_value=httpx.Response(200, json=WEEKS))
    respx.get(f"{B}/stats/weekly").mock(return_value=httpx.Response(200, json={
        "week_key": "2026-09-09", "data": [{"raid_name": "아르모체(4막)", "difficulty": "하드", "count": 7}],
    }))
    respx.get(f"{B}/stats/characters").mock(return_value=httpx.Response(200, json={
        "week_key": "2026-09-09",
        "data": [{"discord_id": "222", "character_name": "메인캐릭", "representative": "메인캐릭", "clears": 3}],
    }))


def test_stats_clears_tab_renders_tables_and_week_select(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_clears()
        resp = client.get("/admin/stats?week_key=2026-09-09")
    body = resp.text
    assert resp.status_code == 200
    assert "아르모체(4막)" in body and ">7<" in body
    assert "메인캐릭" in body and ">3<" in body
    assert 'value="2026-09-09" selected' in body
    assert "/admin/stats/export?kind=weekly&amp;week_key=2026-09-09" in body


def test_stats_activity_tab(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/stats/activity").mock(return_value=httpx.Response(200, json={
            "weekly_parties": [{"week": "2026-37", "count": 4}, {"week": "2026-36", "count": 2}],
            "popular_raids": [{"raid_name": "아르모체(4막)", "difficulty": "하드", "count": 9}],
            "active_users": {"user_count": 12},
        }))
        resp = client.get("/admin/stats?tab=activity")
    body = resp.text
    assert "파티 참여 유저" in body and ">12<" in body
    assert "아르모체(4막) 하드" in body  # 인기 1위 카드
    assert "2026-37" in body


def test_stats_export_csv_has_bom_and_rows(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_clears()
        resp = client.get("/admin/stats/export?kind=weekly&week_key=2026-09-09")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="clears-2026-09-09.csv"' in resp.headers["content-disposition"]
    assert resp.text.startswith("﻿")
    assert "아르모체(4막),하드,7" in resp.text


def test_stats_requires_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/admin/stats")
    assert resp.status_code == 403


def test_notifications_subscriptions_grouped_by_raid(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/subscriptions").mock(return_value=httpx.Response(200, json=[
            {"discord_id": "222", "raid_name": "아르모체(4막)", "difficulty": "하드", "representative": "메인캐릭"},
            {"discord_id": "333", "raid_name": "아르모체(4막)", "difficulty": "하드", "representative": None},
            {"discord_id": "222", "raid_name": "카멘", "difficulty": None, "representative": "메인캐릭"},
        ]))
        resp = client.get("/admin/notifications")
    body = resp.text
    assert "아르모체(4막) 하드" in body and "2명" in body
    assert "카멘 전체" in body
    assert "메인캐릭" in body and "333" in body


def test_notifications_logs_tab(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/notification-logs").mock(return_value=httpx.Response(200, json=[
            {"id": 1, "discord_id": "222", "raid_name": "아르모체(4막)", "difficulty": "하드", "message_id": "900", "sent_at": "2026-09-10 12:00:00"},
        ]))
        resp = client.get("/admin/notifications?tab=logs")
    assert "2026-09-10 12:00:00" in resp.text
    assert "/parties/900" in resp.text


def test_broadcast_posts_and_reports_count(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{B}/notify-all").mock(return_value=httpx.Response(200, json={"success": True, "sent": 20, "total": 22}))
        resp = client.post("/admin/notifications/broadcast", data={"content": "  점검 공지  "})
        respx.get(f"{B}/status").mock(return_value=httpx.Response(200, json={"user_count": 22}))
        page = client.get(resp.headers["location"])
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/notifications?tab=broadcast&sent=20&total=22"
    import json as _json
    assert _json.loads(route.calls[0].request.content) == {"discord_id": "111", "content": "점검 공지"}
    assert "22명 중 20명에게 DM을 보냈습니다" in page.text


def test_completions_page_flow_and_toggle(client, monkeypatch):
    users = [{"discord_id": "222", "representative": "메인캐릭", "registered_at": "2026-05-01T00:00:00", "last_sync": None}]
    raids = {"아르모체(4막)": {"short_name": "4막", "category": "카제로스", "is_active": True,
                          "difficulties": {"노말": {"min_level": 1700, "total_slots": 8}, "하드": {"min_level": 1720, "total_slots": 8}}}}
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/users").mock(return_value=httpx.Response(200, json=users))
        respx.get(f"{B}/users/222/characters").mock(return_value=httpx.Response(200, json=[{"character_name": "메인캐릭", "character_class": "워로드", "item_level": 1710.0}]))
        respx.get(f"{B}/stats/weeks").mock(return_value=httpx.Response(200, json=WEEKS))
        respx.get("http://bot-server.internal/api/internal/raids").mock(return_value=httpx.Response(200, json=raids))
        respx.get(f"{B}/completions").mock(return_value=httpx.Response(200, json={"week_key": "2026-09-09", "completions": ["아르모체(4막)_노말"]}))
        page = client.get("/admin/completions?target_discord_id=222&character_name=메인캐릭&week_key=2026-09-09")
        set_route = respx.post(f"{B}/completions/set").mock(return_value=httpx.Response(200, json={"success": True, "done": True}))
        frag = client.post("/admin/completions/toggle", data={
            "target_discord_id": "222", "character_name": "메인캐릭", "week_key": "2026-09-09",
            "raid_name": "아르모체(4막)", "difficulty": "하드", "done": "1",
        })
    body = page.text
    assert 'id="completion-grid"' in body
    assert body.count("raid-card-diff-toggle done") == 1  # 노말만 완료
    assert frag.status_code == 200 and 'id="completion-grid"' in frag.text
    import json as _json
    sent = _json.loads(set_route.calls[0].request.content)
    assert sent["done"] is True and sent["week_key"] == "2026-09-09" and sent["target_discord_id"] == "222"
