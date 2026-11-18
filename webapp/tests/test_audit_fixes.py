"""감사(2026-11-18) 항목별 회귀 테스트 — 레이드 체크/알림/공대 이벤트/캐릭터 조회/병렬화."""
import asyncio
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from webapp import config, notification_store, party_events, sse
from webapp.routes import events as events_route
from webapp.tests.conftest import log_in, toast_of

B = "http://bot-server.internal/api/internal"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "x", "category": "카제로스", "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "카멘익스": {
        "short_name": "카익", "icon": "x", "category": "카제로스", "is_extreme": True, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}
CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}]
CHARACTERS = [{"character_name": "발키리", "character_class": "서포터", "item_level": 1720.0}]


def _mock_raid_check():
    respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(f"{B}/raid-categories").mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(f"{B}/completions").mock(return_value=httpx.Response(200, json={"week_key": "w", "completions": []}))
    respx.get(f"{B}/raid-selection").mock(return_value=httpx.Response(200, json={"customized": False, "selected_raids": []}))
    respx.get(f"{B}/completions/extreme").mock(return_value=httpx.Response(200, json={"week_key": "w", "raids": []}))


# ── 2. 레이드 체크 토글 검증 ────────────────────────────────────

def test_toggle_rejects_extreme_and_unknown_raids(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        toggle = respx.post(f"{B}/completions/toggle").mock(return_value=httpx.Response(200, json={"completed": True}))
        for raid, diff in (("카멘익스", "노말"), ("없는레이드", "노말"), ("아르모체(4막)", "없는난이도")):
            resp = client.post("/raid-check/toggle", data={
                "raid_name": raid, "difficulty": diff, "character_name": "발키리", "card_index": "0",
            })
            assert resp.status_code == 400, raid
        assert not toggle.called


def test_toggle_rejects_raid_above_character_item_level(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        low = [{**CHARACTERS[0], "item_level": 1600.0}]
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=low))
        toggle = respx.post(f"{B}/completions/toggle").mock(return_value=httpx.Response(200, json={"completed": True}))
        resp = client.post("/raid-check/toggle", data={
            "raid_name": "아르모체(4막)", "difficulty": "노말", "character_name": "발키리", "card_index": "0",
        })
    assert resp.status_code == 400 and not toggle.called


def test_extreme_set_rejects_non_extreme_raid(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        route = respx.post(f"{B}/completions/extreme/set").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/raid-check/extreme/set", data={
            "raid_name": "아르모체(4막)", "difficulty": "노말", "character_name": "발키리",
        })
    assert resp.status_code == 400 and not route.called


# ── 5. 알림 패널: 선택 후 같은 요청에서 읽음 처리 ─────────────────

def test_panel_marks_read_after_select_and_renders_them_as_new(client):
    with respx.mock:
        log_in(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "m1", "새 알림 하나"))

    first = client.get("/notifications/panel")
    assert "새 알림 하나" in first.text
    # 같은 요청에서 이미 읽음 처리됐다 — 안 읽은 수는 0
    assert client.get("/notifications/count").json()["count"] == 0
    # 다음에 열면 "읽음" 쪽으로 간다
    assert asyncio.run(notification_store.list_unread("111")) == []
    assert [n["text"] for n in asyncio.run(notification_store.list_read("111"))] == ["새 알림 하나"]


def test_panel_passes_new_ids_to_template(client):
    with respx.mock:
        log_in(client, discord_id="111")
    client.post("/notifications/subscribe")
    first = asyncio.run(notification_store.add_notification("created", "m1", "하나"))
    seen = {}

    from webapp.templating import templates
    original = templates.TemplateResponse

    def spy(request, name, ctx=None, **kw):
        if name == "_notification_panel.html":
            seen.update(ctx)
        return original(request, name, ctx, **kw)

    templates.TemplateResponse = spy
    try:
        client.get("/notifications/panel")
    finally:
        templates.TemplateResponse = original
    assert seen["new_ids"] == [first["id"]]
    assert [n["id"] for n in seen["items"]] == [first["id"]]


# ── 8. 남의 캐릭터는 cache_only ─────────────────────────────────

def _armory_mock():
    from webapp.tests.test_character_detail_route import DETAIL

    return respx.get(f"{B}/armory-detail").mock(return_value=httpx.Response(200, json=DETAIL))


def test_other_users_character_is_read_cache_only(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = _armory_mock()
        client.get("/characters/발키리", params={"discord_id": "222"})
        client.get("/party-member-card", params={"discord_id": "222", "character_name": "발키리"})
    assert all(parse_qs(urlparse(str(c.request.url)).query).get("cache_only") == ["true"] for c in route.calls)
    assert route.call_count == 2


def test_own_character_is_not_cache_only(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = _armory_mock()
        client.get("/characters/발키리")
        client.get("/characters/발키리", params={"discord_id": "111"})
        client.get("/party-member-card", params={"discord_id": "111", "character_name": "발키리"})
    assert all("cache_only" not in parse_qs(urlparse(str(c.request.url)).query) for c in route.calls)


# ── 11. 독립 호출 병렬화 ────────────────────────────────────────

class _Gauge:
    """동시에 진행 중인 봇 호출 수의 최댓값을 잰다."""

    def __init__(self):
        self.now = 0
        self.peak = 0

    def handler(self, payload):
        async def side_effect(request):
            self.now += 1
            self.peak = max(self.peak, self.now)
            await asyncio.sleep(0.05)
            self.now -= 1
            return httpx.Response(200, json=payload)
        return side_effect


def test_party_detail_calls_run_concurrently(client):
    party = {
        "message_id": "p1", "channel_id": "1", "guild_id": "g", "leader_id": "111", "raid_name": "아르모체(4막)",
        "difficulty": "노말", "proficiency": "숙련", "scheduled_time": "x", "scheduled_datetime": "2026-05-20T20:00:00+09:00",
        "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": "", "slots": [],
    }
    gauge = _Gauge()
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(f"{B}/parties/p1").mock(return_value=httpx.Response(200, json=party))
        respx.get(f"{B}/parties/p1/comments").mock(side_effect=gauge.handler([]))
        respx.get(f"{B}/raids").mock(side_effect=gauge.handler(RAIDS))
        respx.get(f"{B}/parties/p1/eligibility").mock(side_effect=gauge.handler({"can_join": False, "reason": "x"}))
        respx.get(f"{B}/parties/p1/waitlist-status").mock(side_effect=gauge.handler({"on_waitlist": False}))
        respx.get(f"{B}/parties/p1/invitable-users").mock(side_effect=gauge.handler({"success": True, "users": [], "available_slots": []}))
        respx.get(f"{B}/parties/proficiency-options").mock(side_effect=gauge.handler([]))
        resp = client.get("/parties/p1")
    assert resp.status_code == 200
    assert gauge.peak >= 4


def test_expedition_and_settings_calls_run_concurrently(client):
    gauge = _Gauge()
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(f"{B}/user-characters-grouped").mock(side_effect=gauge.handler(CHARACTERS))
        respx.get(f"{B}/accounts/list").mock(side_effect=gauge.handler([]))
        client.get("/expedition")
        assert gauge.peak >= 2

        gauge.peak = 0
        respx.get(f"{B}/raids").mock(side_effect=gauge.handler(RAIDS))
        respx.get(f"{B}/subscriptions").mock(side_effect=gauge.handler([]))
        respx.get(f"{B}/preferences").mock(side_effect=gauge.handler({"pre_notify_hours": 0}))
        resp = client.get("/settings")
    assert resp.status_code == 200 and gauge.peak >= 3


# ── 14. 봇 거부를 성공으로 표시하지 않는다 ──────────────────────

def test_extreme_clear_failure_shows_error_toast(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        respx.post(f"{B}/completions/extreme/clear").mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "해제할 수 없습니다."})
        )
        resp = client.post("/raid-check/extreme/clear", data={"raid_name": "카멘익스"})
    assert toast_of(resp.headers["location"]) == ("해제할 수 없습니다.", "error")


def test_raid_select_save_failure_shows_error_toast(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        respx.post(f"{B}/raid-selection").mock(return_value=httpx.Response(200, json={"success": False, "reason": "저장 실패 사유"}))
        resp = client.post("/raid-check/select/발키리", data={"raid_names": ["아르모체(4막)"]})
    assert toast_of(resp.headers["location"]) == ("저장 실패 사유", "error")


def test_discord_subscription_remove_failure_shows_error_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/subscriptions/remove").mock(return_value=httpx.Response(200, json={"success": False, "reason": "없는 구독"}))
        resp = client.post("/settings/discord-subscriptions/remove", data={"raid_name": "카멘", "difficulty": "하드"})
    assert toast_of(resp.headers["location"]) == ("없는 구독", "error")


def test_admin_completion_toggle_failure_shows_error_toast(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    from webapp.routes import admin

    async def fake_grid(*a, **k):
        return {"rows": []}

    monkeypatch.setattr(admin, "_completion_grid", fake_grid)
    monkeypatch.setattr(admin.templates, "TemplateResponse", lambda request, name, ctx, headers=None: __import__("starlette.responses", fromlist=["x"]).Response("ok", headers=headers))
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(f"{B}/admin/completions/set").mock(return_value=httpx.Response(200, json={"success": False, "reason": "권한 없음"}))
        resp = client.post("/admin/completions/toggle", data={
            "target_discord_id": "222", "character_name": "a", "week_key": "w", "raid_name": "r", "difficulty": "d", "done": "1",
        })
    assert resp.headers["X-Toast-Type"] == "error"


# ── 19. 모든 난이도 필터 중복 ───────────────────────────────────

def test_all_difficulty_filter_is_not_duplicated(notification_db):
    async def scenario():
        for _ in range(3):
            await notification_store.add_raid_filter("111", "카멘", None)
        prefs = await notification_store.get_preferences("111")
        assert prefs["raid_filters"] == [{"raid_name": "카멘", "difficulty": None}]
        await notification_store.remove_raid_filter("111", "카멘", None)
        assert (await notification_store.get_preferences("111"))["raid_filters"] == []

    asyncio.run(scenario())


def test_migration_dedupes_existing_null_filter_rows(notification_db):
    con = sqlite3.connect(notification_db)
    con.executescript("""
        DROP TABLE notification_raid_filters;
        CREATE TABLE notification_raid_filters (discord_id TEXT NOT NULL, raid_name TEXT NOT NULL, difficulty TEXT,
            PRIMARY KEY (discord_id, raid_name, difficulty));
        INSERT INTO notification_raid_filters VALUES ('1','카멘',NULL),('1','카멘',NULL),('1','카멘',NULL),
            ('1','카멘','하드'),('2','에기르',NULL),('2','에기르','');
    """)
    con.commit()
    con.close()

    asyncio.run(notification_store.init_db())
    asyncio.run(notification_store.init_db())  # 두 번 돌려도 같은 결과(멱등)

    con = sqlite3.connect(notification_db)
    rows = sorted(con.execute("SELECT discord_id, raid_name, difficulty FROM notification_raid_filters").fetchall())
    con.close()
    assert rows == [("1", "카멘", ""), ("1", "카멘", "하드"), ("2", "에기르", "")]


# ── 18. 알림 커서 영속화 ────────────────────────────────────────

def test_notification_cursor_survives_restart(notification_db, monkeypatch):
    async def no_parties(guild_id):
        return []

    seen_after = []

    async def feed(after_id):
        seen_after.append(after_id)
        if after_id is None:
            return {"latest_id": 10, "items": []}
        return {"latest_id": 12, "items": [{"id": 12, "discord_id": "111", "kind": "invited", "message_id": "p1", "text": "초대"}]}

    monkeypatch.setattr(party_events.bot_client, "list_parties", no_parties)
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None
    asyncio.run(party_events._poll_once())          # 최초: 커서만 잡는다(10)
    assert asyncio.run(notification_store.get_state(party_events.CURSOR_KEY)) == "10"

    # 웹앱 재시작 — 메모리 상태는 사라지고 DB 커서만 남는다
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None
    asyncio.run(party_events._poll_once())
    assert seen_after == [None, 10]                  # 저장된 커서(10)부터 이어서 조회
    assert asyncio.run(notification_store.unread_count("111", personal_only=True)) == 1
    assert asyncio.run(notification_store.get_state(party_events.CURSOR_KEY)) == "12"


def test_notification_cursor_advances_per_item_and_stops_on_store_failure(notification_db, monkeypatch):
    async def no_parties(guild_id):
        return []

    async def feed(after_id):
        if after_id is None:
            return {"latest_id": 0, "items": []}
        return {"latest_id": 3, "items": [
            {"id": i, "discord_id": "111", "kind": "invited", "message_id": "p", "text": f"n{i}"}
            for i in (1, 2, 3) if i > after_id
        ]}

    real_add = notification_store.add_notification
    calls = {"n": 0}

    async def flaky_add(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk")
        return await real_add(*args, **kwargs)

    monkeypatch.setattr(party_events.bot_client, "list_parties", no_parties)
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None
    asyncio.run(party_events._poll_once())  # 커서 0
    monkeypatch.setattr(notification_store, "add_notification", flaky_add)
    asyncio.run(party_events._poll_once())  # 1번만 저장되고 2번에서 실패 → 커서는 1
    assert party_events._last_web_notification_id == 1
    monkeypatch.setattr(notification_store, "add_notification", real_add)
    asyncio.run(party_events._poll_once())  # 2·3 저장 — 1번은 다시 저장되지 않는다
    texts = [n["text"] for n in asyncio.run(notification_store.list_unread("111", personal_only=True))]
    assert sorted(texts) == ["n1", "n2", "n3"] and party_events._last_web_notification_id == 3


# ── 17. 사라진 파티 재시도·저장 실패 재시도 ─────────────────────

PARTY = {"message_id": "1", "status": "recruiting", "raid_name": "카멘", "difficulty": "하드", "slots": []}


def _empty_feed(monkeypatch):
    async def feed(after_id):
        return {"latest_id": 0, "items": []}
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)


def _reset_events():
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None
    party_events._subscribers.clear()
    party_events._notification_subscribers.clear()


def test_failed_party_lookup_is_retried_and_cleared_notification_not_lost(notification_db, monkeypatch):
    _empty_feed(monkeypatch)
    _reset_events()
    polls = {"n": 0}

    async def list_parties(guild_id):
        polls["n"] += 1
        return [PARTY] if polls["n"] == 1 else []

    lookups = {"n": 0}

    async def get_party(message_id):
        lookups["n"] += 1
        if lookups["n"] == 1:
            raise RuntimeError("bot down")
        return {**PARTY, "status": "disbanded"}

    monkeypatch.setattr(party_events.bot_client, "list_parties", list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", get_party)
    notif_q = party_events.subscribe_notifications()
    sse_q = party_events.subscribe()
    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())          # 사라짐 감지 + 조회 실패
    assert notif_q.empty() and sse_q.get_nowait() == {"type": "removed", "message_id": "1"}  # 목록은 바로 갱신
    asyncio.run(party_events._poll_once())          # 재시도 성공
    assert notif_q.get_nowait()["type"] == "cleared"
    assert sse_q.get_nowait() == {"type": "cleared", "message_id": "1"}
    asyncio.run(party_events._poll_once())
    assert notif_q.empty()                           # 중복 없음


def test_notification_store_failure_is_retried_without_duplicates(notification_db, monkeypatch):
    _empty_feed(monkeypatch)
    _reset_events()
    polls = {"n": 0}

    async def list_parties(guild_id):
        polls["n"] += 1
        return [] if polls["n"] == 1 else [PARTY]

    real_add = notification_store.add_notification
    fail = {"on": True}

    async def flaky(*a, **k):
        if fail["on"]:
            raise RuntimeError("locked")
        return await real_add(*a, **k)

    monkeypatch.setattr(party_events.bot_client, "list_parties", list_parties)
    monkeypatch.setattr(notification_store, "add_notification", flaky)
    notif_q = party_events.subscribe_notifications()
    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())           # 생성 감지 → 저장 실패
    assert notif_q.empty()
    fail["on"] = False
    asyncio.run(party_events._poll_once())           # 같은 알림이 이어서 저장된다(스냅샷은 이미 앞서 있어도)
    asyncio.run(party_events._poll_once())
    assert notif_q.get_nowait()["type"] == "created" and notif_q.empty()


# ── 4. 되살아난·관리자 종료 파티는 잘못된 알림을 내지 않는다 ─────

def test_reopened_party_does_not_announce_recruitment_start(notification_db, monkeypatch):
    _empty_feed(monkeypatch)
    _reset_events()
    sequence = [[PARTY], [], [PARTY]]

    async def list_parties(guild_id):
        return sequence.pop(0)

    async def get_party(message_id):
        return {**PARTY, "status": "disbanded"}

    monkeypatch.setattr(party_events.bot_client, "list_parties", list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", get_party)
    notif_q = party_events.subscribe_notifications()
    sse_q = party_events.subscribe()
    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())           # 클리어
    assert notif_q.get_nowait()["type"] == "cleared"
    sse_q.get_nowait()
    asyncio.run(party_events._poll_once())           # 클리어 되돌리기로 다시 나타남
    assert notif_q.empty()
    assert sse_q.get_nowait() == {"type": "reopened", "message_id": "1"}


def test_admin_disband_hint_suppresses_cleared_notification(notification_db, monkeypatch):
    _empty_feed(monkeypatch)
    _reset_events()
    sequence = [[PARTY], []]

    async def list_parties(guild_id):
        return sequence.pop(0)

    async def get_party(message_id):
        return {**PARTY, "status": "disbanded"}

    monkeypatch.setattr(party_events.bot_client, "list_parties", list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", get_party)
    notif_q = party_events.subscribe_notifications()
    sse_q = party_events.subscribe()
    asyncio.run(party_events._poll_once())
    party_events.note_admin_action("1", "disband")
    asyncio.run(party_events._poll_once())
    assert notif_q.empty()
    assert sse_q.get_nowait() == {"type": "removed", "message_id": "1"}


def test_admin_disband_and_revert_routes_leave_hints(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(f"{B}/admin/parties/p1/disband").mock(return_value=httpx.Response(200, json={"success": True}))
        respx.post(f"{B}/admin/parties/p1/revert-clear").mock(return_value=httpx.Response(200, json={"success": False, "reason": "x"}))
        client.post("/parties/p1/admin-disband")
        assert party_events._admin_hints["p1"][0] == "disband"
        client.post("/parties/p1/admin-revert-clear")  # 실패했으니 힌트를 남기지 않는다
        assert "p1" not in party_events._admin_hints


# ── 9. SSE 이벤트는 종류와 message_id를 싣는다 ─────────────────

def test_change_events_carry_type_and_message_id(monkeypatch):
    _empty_feed(monkeypatch)
    base = {"message_id": "7", "status": "recruiting", "raid_name": "카멘", "difficulty": "하드", "slots": [], "comment_count": 0}
    cases = {
        "slots": {**base, "slots": [{"slot_number": 1, "discord_id": "1"}]},
        "status": {**base, "status": "full"},
        "details": {**base, "memo": "음성"},
        "comments": {**base, "comment_count": 1},
    }
    for kind, changed in cases.items():
        events = party_events._detect_change_events({"7": base}, {"7": changed})
        assert events == [{"type": kind, "message_id": "7"}], kind


def test_events_route_renders_json_payload():
    chunk = events_route._render({"type": "comments", "message_id": "7"})
    assert chunk.startswith("event: parties-changed\ndata: ")
    payload = json.loads(chunk.split("data: ", 1)[1])
    assert payload == {"type": "comments", "message_id": "7"}


def test_keepalive_and_stream_are_shared_between_event_routes():
    from webapp.routes import notifications

    assert not hasattr(events_route, "KEEPALIVE_INTERVAL_SECONDS")
    assert not hasattr(notifications, "KEEPALIVE_INTERVAL_SECONDS")
    assert sse.KEEPALIVE_INTERVAL_SECONDS == 15


# ── 10. party-live.js 계약(배너 마크업·이벤트 종류 필터) ─────────

def test_party_live_js_contract():
    js = (Path(__file__).resolve().parents[1] / "static" / "party-live.js").read_text(encoding="utf-8")
    assert 'banner.className = "banner info"' in js
    assert "바뀐 내용이 있습니다" in js and "지금 반영" in js and '"btn sm pri"' in js
    assert "JSON.parse(e.data)" in js and "isRelevant" in js
    assert 'event.type === "cleared"' in js  # 레이드 체크는 클리어에만 반응
    assert "String(event.message_id) === detailId" in js  # 상세는 자기 공대에만 반응
    assert "form[data-live-dirty]" in js


# ── 정리: 사용하지 않는 레거시 쿼리 파라미터 ────────────────────

def test_party_create_page_no_longer_builds_groups_json():
    src = (Path(__file__).resolve().parents[1] / "routes" / "party.py").read_text(encoding="utf-8")
    assert "groups_json" not in src
