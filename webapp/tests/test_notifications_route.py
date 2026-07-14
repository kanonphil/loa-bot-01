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
    saved = asyncio.run(notification_store.add_notification("created", "msg-1", "text"))

    resp = client.get(f"/notifications/{saved['id']}/open")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/msg-1"

    resp = client.get("/notifications/panel")
    assert "새 알림이 없습니다" in resp.text


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
