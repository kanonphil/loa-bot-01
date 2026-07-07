"""공대 목록 변경 감지(party_events) 검증 — 실제 SSE 연결 없이 폴링/알림 로직만 단위 테스트."""
import asyncio

import pytest

from webapp import party_events

PARTY_A = {"message_id": "1", "status": "recruiting", "slots": [{"discord_id": "111"}]}
PARTY_A_MORE_SLOTS = {"message_id": "1", "status": "recruiting", "slots": [{"discord_id": "111"}, {"discord_id": "222"}]}
PARTY_B = {"message_id": "2", "status": "recruiting", "slots": []}


@pytest.fixture(autouse=True)
def _reset_state():
    party_events._subscribers.clear()
    party_events._last_fingerprint = None
    yield
    party_events._subscribers.clear()
    party_events._last_fingerprint = None


def test_fingerprint_changes_when_slot_count_changes():
    fp1 = party_events._fingerprint([PARTY_A])
    fp2 = party_events._fingerprint([PARTY_A_MORE_SLOTS])
    assert fp1 != fp2


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

    monkeypatch.setattr(party_events.bot_client, "list_parties", fake_list_parties)
    queue = party_events.subscribe()
    asyncio.run(party_events._poll_once())

    party_events.unsubscribe(queue)
    asyncio.run(party_events._poll_once())

    assert queue.empty()
