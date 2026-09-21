"""알림 종 아이콘/이력/설정 라우트 검증 — SSE 스트림은 events.py 테스트 패턴을 재사용."""
import asyncio

import pytest
import respx

from webapp import notification_store, party_events
from webapp.routes import notifications
from webapp.tests.conftest import log_in


@pytest.fixture(autouse=True)
def _reset_notification_subscribers():
    party_events._notification_subscribers.clear()
    yield
    party_events._notification_subscribers.clear()


class _FakeRequest:
    async def is_disconnected(self):
        return False


def _login(client, discord_id="111"):
    with respx.mock:
        log_in(client, discord_id=discord_id)


def test_count_requires_login(client):
    resp = client.get("/notifications/count")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_panel_requires_login(client):
    resp = client.get("/notifications/panel")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_settings_requires_login(client):
    resp = client.get("/settings")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_open_requires_login(client):
    resp = client.get("/notifications/1/open")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_count_default_not_subscribed_and_zero(client):
    _login(client)
    resp = client.get("/notifications/count")
    assert resp.json() == {"subscribed": False, "count": 0}


def test_panel_prompts_to_subscribe_when_not_subscribed(client):
    _login(client)
    resp = client.get("/notifications/panel")
    assert "구독하면" in resp.text


def test_settings_toggle_subscribe(client):
    _login(client)

    resp = client.get("/settings")
    assert "구독하기" in resp.text

    resp = client.post("/notifications/subscribe")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings"

    resp = client.get("/settings")
    assert "구독 중" in resp.text


def test_count_reflects_unread_after_subscribing(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")

    asyncio.run(notification_store.add_notification("created", "msg-1", "카멘 하드 공격대가 모집을 시작했습니다."))

    resp = client.get("/notifications/count")
    assert resp.json() == {"subscribed": True, "count": 1}


def test_panel_lists_unread_when_subscribed(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "msg-1", "카멘 하드 공격대가 모집을 시작했습니다."))

    resp = client.get("/notifications/panel")
    assert "카멘 하드 공격대가 모집을 시작했습니다." in resp.text
    assert "/notifications/1/open" in resp.text
    # 드롭다운 헤더 + 종류별 아이콘 칩 + 상대 시각
    assert "notif-panel-header" in resp.text
    assert "notif-icon-created" in resp.text
    assert "방금 전" in resp.text


def test_time_ago_buckets():
    """알림 시각의 상대 표기 — 방금/분/시간/일 구간."""
    from datetime import datetime, timedelta, timezone

    from webapp.routes.notifications import _time_ago

    now = datetime.now(timezone.utc)
    assert _time_ago(now.isoformat()) == "방금 전"
    assert _time_ago((now - timedelta(minutes=5)).isoformat()) == "5분 전"
    assert _time_ago((now - timedelta(hours=3)).isoformat()) == "3시간 전"
    assert _time_ago((now - timedelta(days=2)).isoformat()) == "2일 전"
    assert _time_ago("이상한 값") == ""
    assert _time_ago(None) == ""


def test_open_marks_read_and_redirects_to_party(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    saved = asyncio.run(notification_store.add_notification("created", "msg-1", "읽음 처리될 알림"))

    resp = client.get(f"/notifications/{saved['id']}/open")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/msg-1"

    resp = client.get("/notifications/panel")
    assert "새 알림이 없습니다" in resp.text
    # 읽은 알림은 "읽음" 탭 pane으로 이동
    assert 'data-notif-pane="read"' in resp.text
    assert "읽음 처리될 알림" in resp.text


def test_read_all_marks_everything_and_moves_to_read_tab(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "msg-1", "알림 하나"))
    asyncio.run(notification_store.add_notification("cleared", "msg-2", "알림 둘"))
    assert client.get("/notifications/count").json()["count"] == 2

    resp = client.post("/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}

    # 배지 0, 둘 다 읽음 탭으로 이동
    assert client.get("/notifications/count").json()["count"] == 0
    panel = client.get("/notifications/panel").text
    assert "알림 하나" in panel and "알림 둘" in panel
    assert "새 알림이 없습니다" in panel  # 안읽음 pane은 비어있음


def test_panel_has_unread_and_read_tabs(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "msg-1", "안 읽은 알림"))

    resp = client.get("/notifications/panel")
    assert 'data-notif-tab="unread"' in resp.text
    assert 'data-notif-tab="read"' in resp.text
    assert "안 읽은 알림" in resp.text
    assert "읽은 알림이 없습니다" in resp.text  # 읽음 pane은 비어있음


def test_open_unknown_notification_redirects_to_party_list(client):
    _login(client, discord_id="111")
    resp = client.get("/notifications/9999/open")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties"


def test_unsubscribed_user_does_not_accumulate_unread(client):
    """구독 안 한 유저는 알림이 쌓여도 count/panel에 아무것도 안 보여야 한다(toast만 받음)."""
    _login(client, discord_id="111")
    asyncio.run(notification_store.add_notification("created", "msg-1", "text"))

    resp = client.get("/notifications/count")
    assert resp.json() == {"subscribed": False, "count": 0}


def test_settings_page_shows_type_checkboxes_and_sound_section(client):
    _login(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "알림 종류" in resp.text
    assert 'name="created"' in resp.text
    assert 'name="cleared"' in resp.text
    assert 'name="guest_joined"' in resp.text
    assert "레이드 필터" in resp.text
    assert "알림 소리" in resp.text
    assert "notif-sound-toggle" in resp.text


def test_save_type_preferences_filters_panel(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "msg-1", "모집 알림"))
    asyncio.run(notification_store.add_notification("cleared", "msg-2", "클리어 알림"))

    # 모집 알림 끄기 (체크 안 된 항목은 폼에서 빠짐)
    resp = client.post("/notifications/preferences", data={"cleared": "on", "guest_joined": "on"})
    assert resp.status_code == 303

    resp = client.get("/notifications/panel")
    assert "클리어 알림" in resp.text
    assert "모집 알림" not in resp.text
    assert client.get("/notifications/count").json()["count"] == 1


def test_raid_filter_add_and_remove_roundtrip(client):
    _login(client, discord_id="111")
    client.post("/notifications/subscribe")
    asyncio.run(notification_store.add_notification("created", "m1", "카멘 하드 모집", raid_name="카멘", difficulty="하드"))
    asyncio.run(notification_store.add_notification("created", "m2", "종막 하드 모집", raid_name="종막", difficulty="하드"))

    resp = client.post("/notifications/raid-filters/add", data={"raid_name": "카멘", "difficulty": "하드"})
    assert resp.status_code == 303

    resp = client.get("/notifications/panel")
    assert "카멘 하드 모집" in resp.text
    assert "종막 하드 모집" not in resp.text

    # 설정 페이지에 필터 목록 표시
    resp = client.get("/settings")
    assert "카멘" in resp.text

    # 필터 삭제 → 다시 전체 레이드
    resp = client.post("/notifications/raid-filters/remove", data={"raid_name": "카멘", "difficulty": "하드"})
    assert resp.status_code == 303
    resp = client.get("/notifications/panel")
    assert "종막 하드 모집" in resp.text


def test_stream_filters_events_by_user_preferences(monkeypatch, notification_db):
    """실시간 toast(SSE)도 종류 토글을 따라야 한다 — created를 끈 유저에겐
    created 이벤트가 스킵되고 다음 이벤트(cleared)만 전달된다."""
    monkeypatch.setattr(notifications, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def scenario():
        await notification_store.set_type_preferences("111", created=False, cleared=True, guest_joined=True)
        gen = notifications._stream(_FakeRequest(), discord_id="111")
        first = await gen.__anext__()
        assert first.startswith(":")  # keep-alive로 구독 등록

        queue = next(iter(party_events._notification_subscribers))
        queue.put_nowait({"id": 1, "type": "created", "message_id": "m1", "text": "모집", "raid_name": "카멘", "difficulty": "하드"})
        queue.put_nowait({"id": 2, "type": "cleared", "message_id": "m2", "text": "클리어", "raid_name": "카멘", "difficulty": "하드"})
        event = await gen.__anext__()
        assert "cleared" in event
        assert "모집" not in event
        await gen.aclose()

    asyncio.run(scenario())


def test_stream_sends_keepalive_then_notification_event(monkeypatch):
    monkeypatch.setattr(notifications, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def scenario():
        gen = notifications._stream(_FakeRequest())
        first = await gen.__anext__()
        assert first.startswith(":")

        queue = next(iter(party_events._notification_subscribers))
        queue.put_nowait({"id": 1, "type": "created", "message_id": "msg-1", "text": "카멘 하드 공격대가 모집을 시작했습니다."})
        second = await gen.__anext__()
        assert second.startswith("event: notification")
        assert "카멘 하드 공격대가 모집을 시작했습니다." in second
        await gen.aclose()

    asyncio.run(scenario())


def test_stream_unsubscribes_on_close(monkeypatch):
    monkeypatch.setattr(notifications, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def scenario():
        gen = notifications._stream(_FakeRequest())
        assert len(party_events._notification_subscribers) == 0
        await gen.__anext__()
        assert len(party_events._notification_subscribers) == 1
        await gen.aclose()
        assert len(party_events._notification_subscribers) == 0

    asyncio.run(scenario())


# ── 디스코드 DM 구독 / 사전 알림 (봇 DB 설정을 웹 설정 페이지에서) ──────────

import httpx
import respx as _respx

SUBSCRIPTIONS_URL = "http://bot-server.internal/api/internal/subscriptions"
PREFERENCES_URL = "http://bot-server.internal/api/internal/preferences"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스", "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}


def _mock_bot_settings(subscriptions=None, hours=0.0):
    _respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    _respx.get(SUBSCRIPTIONS_URL).mock(return_value=httpx.Response(200, json=subscriptions or []))
    _respx.get(PREFERENCES_URL).mock(return_value=httpx.Response(200, json={"pre_notify_hours": hours, "choices": [0.0, 0.5, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0]}))


def test_settings_page_shows_discord_subscriptions_and_pre_notify(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        _mock_bot_settings(subscriptions=[{"raid_name": "아르모체(4막)", "difficulty": "전체", "created_at": "2026-05-01"}], hours=2.0)
        resp = client.get("/settings")

    body = resp.text
    assert "디스코드 DM 구독" in body
    assert "전체 난이도" in body
    assert 'action="/settings/discord-subscriptions/remove"' in body
    assert "공대 시작 사전 알림" in body
    assert 'value="2.0" selected' in body
    assert "30분 전" in body and "받지 않음" in body


def test_settings_page_degrades_when_bot_is_down(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        _respx.get(RAIDS_URL).mock(return_value=httpx.Response(500, text="boom"))
        resp = client.get("/settings")

    assert resp.status_code == 200
    assert resp.text.count("봇 서버에 연결하지 못해") == 2
    assert "알림 종류" in resp.text  # 웹 알림 설정은 그대로 동작


def test_add_discord_subscription_posts_to_bot(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        route = _respx.post(SUBSCRIPTIONS_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/settings/discord-subscriptions/add", data={"raid_name": "아르모체(4막)", "difficulty": ""})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?saved=subscription"
    import json as _json
    assert _json.loads(route.calls[0].request.content) == {"discord_id": "111", "raid_name": "아르모체(4막)", "difficulty": "전체"}


def test_add_discord_subscription_failure_shows_reason(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        _respx.post(SUBSCRIPTIONS_URL).mock(return_value=httpx.Response(200, json={"success": False, "reason": "이미 구독 중입니다."}))
        resp = client.post("/settings/discord-subscriptions/add", data={"raid_name": "아르모체(4막)", "difficulty": "노말"})

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/settings?error=")


def test_remove_discord_subscription(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        route = _respx.post(SUBSCRIPTIONS_URL + "/remove").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/settings/discord-subscriptions/remove", data={"raid_name": "아르모체(4막)", "difficulty": "노말"})

    assert resp.status_code == 303
    assert route.called


def test_save_pre_notify_hours(client):
    with _respx.mock:
        log_in(client, discord_id="111")
        route = _respx.post(PREFERENCES_URL).mock(return_value=httpx.Response(200, json={"success": True, "pre_notify_hours": 1.0}))
        resp = client.post("/settings/pre-notify", data={"pre_notify_hours": "1.0"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?saved=pre_notify"
    import json as _json
    assert _json.loads(route.calls[0].request.content) == {"discord_id": "111", "pre_notify_hours": 1.0}
