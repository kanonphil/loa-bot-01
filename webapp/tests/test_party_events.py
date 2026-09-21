"""공대 목록 변경 감지(party_events) 검증 — 실제 SSE 연결 없이 폴링/알림 로직만 단위 테스트."""
import asyncio

import pytest

from webapp import config, notification_store, party_events

PARTY_A = {
    "message_id": "1", "status": "recruiting", "raid_name": "카멘", "difficulty": "하드",
    "slots": [{"discord_id": "111", "is_guest": False}],
}
PARTY_A_MORE_SLOTS = {
    "message_id": "1", "status": "recruiting", "raid_name": "카멘", "difficulty": "하드",
    "slots": [{"discord_id": "111", "is_guest": False}, {"discord_id": "222", "is_guest": False}],
}
PARTY_A_GUEST_JOINED = {
    "message_id": "1", "status": "recruiting", "raid_name": "카멘", "difficulty": "하드",
    "slots": [{"discord_id": "111", "is_guest": False}, {"discord_id": "999", "is_guest": True}],
}
PARTY_B = {
    "message_id": "2", "status": "recruiting", "raid_name": "에기르", "difficulty": "노말",
    "slots": [],
}


@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_DB_PATH", str(tmp_path / "notif_test.db"))
    asyncio.run(notification_store.init_db())

    party_events._subscribers.clear()
    party_events._last_fingerprint = None
    party_events._notification_subscribers.clear()
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None

    # 봇의 개인 알림 큐 — 기본은 비어 있음(개별 테스트가 덮어쓴다)
    async def empty_feed(after_id):
        return {"latest_id": 0, "items": []}

    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", empty_feed)
    yield
    party_events._subscribers.clear()
    party_events._last_fingerprint = None
    party_events._notification_subscribers.clear()
    party_events._last_snapshot = None
    party_events._last_web_notification_id = None


def test_fingerprint_changes_when_slot_count_changes():
    fp1 = party_events._fingerprint([PARTY_A])
    fp2 = party_events._fingerprint([PARTY_A_MORE_SLOTS])
    assert fp1 != fp2


def test_fingerprint_changes_when_schedule_or_difficulty_changes():
    """인원수가 그대로여도 일정/난이도/메모/파티장이 바뀌면 열린 탭이 갱신돼야 한다."""
    base = {**PARTY_A, "scheduled_datetime": "2026-05-20T20:00:00+09:00", "difficulty": "하드", "memo": None}
    assert party_events._fingerprint([base]) != party_events._fingerprint([{**base, "scheduled_datetime": "2026-05-21T20:00:00+09:00"}])
    assert party_events._fingerprint([base]) != party_events._fingerprint([{**base, "difficulty": "노말"}])
    assert party_events._fingerprint([base]) != party_events._fingerprint([{**base, "memo": "음성 필수"}])
    assert party_events._fingerprint([base]) != party_events._fingerprint([{**base, "leader_id": "222"}])


def test_fingerprint_changes_on_one_in_one_out():
    swapped = {**PARTY_A, "slots": [{"discord_id": "333", "is_guest": False}]}
    assert party_events._fingerprint([PARTY_A]) != party_events._fingerprint([swapped])


def test_fingerprint_stable_for_identical_input():
    assert party_events._fingerprint([PARTY_A, PARTY_B]) == party_events._fingerprint([PARTY_A, PARTY_B])


def test_first_poll_does_not_notify_subscribers(monkeypatch):
    """서버가 막 시작했을 때(첫 폴링)는 '변경'이 아니라 기준점을 세우는 것뿐이라 알림이 없어야 한다."""
    async def fake_list_parties(guild_id):
        return [PARTY_A]

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    queue = party_events.subscribe()

    asyncio.run(party_events._poll_once())

    assert queue.empty()


def test_poll_notifies_subscribers_when_parties_change(monkeypatch):
    calls = {"n": 0}

    async def fake_list_parties(guild_id):
        calls["n"] += 1
        return [PARTY_A] if calls["n"] == 1 else [PARTY_A_MORE_SLOTS]

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    queue = party_events.subscribe()

    asyncio.run(party_events._poll_once())  # 기준점 수립 — 알림 없음
    assert queue.empty()

    asyncio.run(party_events._poll_once())  # 변경 감지 — 알림 발생
    assert not queue.empty()


def test_poll_does_not_notify_when_nothing_changed(monkeypatch):
    async def fake_list_parties(guild_id):
        return [PARTY_A]

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    queue = party_events.subscribe()

    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())

    assert queue.empty()


def test_unsubscribe_stops_further_notifications(monkeypatch):
    calls = {"n": 0}

    async def fake_list_parties(guild_id):
        calls["n"] += 1
        return [PARTY_A] if calls["n"] == 1 else [PARTY_B]

    async def fake_get_party(message_id):
        return None  # 파티 "1"은 취소/삭제된 것으로 취급 — 클리어 알림 없음

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", fake_get_party)
    queue = party_events.subscribe()
    asyncio.run(party_events._poll_once())

    party_events.unsubscribe(queue)
    asyncio.run(party_events._poll_once())

    assert queue.empty()


# ── 알림 이벤트 감지 ──────────────────────────────────────────

def test_detect_notification_events_created():
    events = party_events._detect_notification_events({}, {"1": PARTY_A})
    assert events == [{
        "type": "created",
        "message_id": "1",
        "text": "카멘 하드 공격대가 모집을 시작했습니다.",
        "raid_name": "카멘",  # 레이드 필터(봇의 /레이드구독 대응) 매칭용 메타데이터
        "difficulty": "하드",
    }]


def test_detect_notification_events_guest_joined():
    prev = {"1": PARTY_A}
    current = {"1": PARTY_A_GUEST_JOINED}
    events = party_events._detect_notification_events(prev, current)
    assert events == [{
        "type": "guest_joined",
        "message_id": "1",
        "text": "카멘 하드 공대에 게스트가 합류했습니다.",
        "raid_name": "카멘",
        "difficulty": "하드",
    }]


def test_detect_notification_events_no_change():
    prev = {"1": PARTY_A}
    current = {"1": PARTY_A}
    assert party_events._detect_notification_events(prev, current) == []


def test_poll_once_persists_and_broadcasts_created_event(monkeypatch):
    calls = {"n": 0}

    async def fake_list_parties(guild_id):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [PARTY_A]

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    notif_queue = party_events.subscribe_notifications()

    asyncio.run(party_events._poll_once())  # 기준점 수립 — 알림 없음
    assert notif_queue.empty()

    asyncio.run(party_events._poll_once())  # 생성 감지
    assert not notif_queue.empty()
    event = notif_queue.get_nowait()
    assert event["type"] == "created"
    assert event["message_id"] == "1"

    async def check_persisted():
        await notification_store.set_subscribed("111", True)
        return await notification_store.list_unread("111")

    unread = asyncio.run(check_persisted())
    assert len(unread) == 1
    assert unread[0]["type"] == "created"


def test_poll_once_detects_cleared_party(monkeypatch):
    calls = {"n": 0}

    async def fake_list_parties(guild_id):
        calls["n"] += 1
        return [PARTY_A] if calls["n"] == 1 else []

    async def fake_get_party(message_id):
        return {**PARTY_A, "status": "disbanded"}

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", fake_get_party)
    notif_queue = party_events.subscribe_notifications()

    asyncio.run(party_events._poll_once())  # 기준점 수립
    assert notif_queue.empty()

    asyncio.run(party_events._poll_once())  # 파티 소멸 + 상태 disbanded -> 클리어로 판정
    assert not notif_queue.empty()
    event = notif_queue.get_nowait()
    assert event["type"] == "cleared"
    assert event["message_id"] == "1"


def test_poll_once_ignores_cancelled_party(monkeypatch):
    """get_party가 None을 반환하면(완전히 삭제된 취소 파티) 클리어 알림을 만들지 않는다."""
    calls = {"n": 0}

    async def fake_list_parties(guild_id):
        calls["n"] += 1
        return [PARTY_A] if calls["n"] == 1 else []

    async def fake_get_party(message_id):
        return None

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_party", fake_get_party)
    notif_queue = party_events.subscribe_notifications()

    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())

    assert notif_queue.empty()


# ── 봇 개인 알림(web_notifications) 수집 ────────────────────────

def test_first_web_notification_poll_only_sets_cursor(monkeypatch):
    async def fake_list_parties(guild_id):
        return []

    async def feed(after_id):
        assert after_id is None
        return {"latest_id": 41, "items": [{"id": 41, "discord_id": "111", "kind": "kicked", "message_id": "1", "text": "x"}]}

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)
    queue = party_events.subscribe_notifications()
    asyncio.run(party_events._poll_once())
    assert party_events._last_web_notification_id == 41
    assert queue.empty()  # 기동 직후 지난 알림은 다시 뿌리지 않는다
    assert asyncio.run(notification_store.unread_count("111", personal_only=True)) == 0


def test_web_notifications_are_stored_as_personal_and_fanned_out(monkeypatch):
    async def fake_list_parties(guild_id):
        return []

    calls = []

    async def feed(after_id):
        calls.append(after_id)
        if after_id is None:
            return {"latest_id": 10, "items": []}
        return {"latest_id": 12, "items": [
            {"id": 11, "discord_id": "111", "kind": "invited", "message_id": "p1", "text": "초대됨"},
            {"id": 12, "discord_id": "222", "kind": "kicked", "message_id": "p1", "text": "퇴장됨"},
        ]}

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)
    queue = party_events.subscribe_notifications()
    asyncio.run(party_events._poll_once())
    asyncio.run(party_events._poll_once())

    assert calls == [None, 10]
    assert party_events._last_web_notification_id == 12
    events = [queue.get_nowait() for _ in range(2)]
    assert [e["target_discord_id"] for e in events] == ["111", "222"]
    assert events[0]["type"] == "invited"
    # 구독 안 한 유저도 본인 것만 보이고, 남의 개인 알림은 안 보인다
    assert asyncio.run(notification_store.unread_count("111", personal_only=True)) == 1
    assert asyncio.run(notification_store.unread_count("222", personal_only=True)) == 1
    assert asyncio.run(notification_store.unread_count("333", personal_only=True)) == 0


def test_web_notification_feed_failure_does_not_break_party_polling(monkeypatch):
    async def fake_list_parties(guild_id):
        return [PARTY_A]

    async def feed(after_id):
        raise RuntimeError("bot down")

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    monkeypatch.setattr(party_events.bot_client, "get_web_notifications", feed)
    asyncio.run(party_events._poll_once())
    assert party_events._last_fingerprint is not None
