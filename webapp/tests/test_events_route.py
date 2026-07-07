"""공대 실시간 반영 SSE 엔드포인트(/events/parties) 검증."""
import asyncio

import pytest

from webapp import party_events
from webapp.routes import events


@pytest.fixture(autouse=True)
def _reset_party_events_state():
    party_events._subscribers.clear()
    party_events._last_fingerprint = None
    yield
    party_events._subscribers.clear()
    party_events._last_fingerprint = None


class _FakeRequest:
    async def is_disconnected(self):
        return False


def test_requires_login(client):
    resp = client.get("/events/parties")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_stream_sends_keepalive_then_change_event(monkeypatch):
    """구독 직후엔 큐가 비어있으니 keep-alive가 먼저 오고, 변경 이벤트가 큐에 들어오면
    그 다음 청크로 parties-changed 이벤트가 내려가야 한다."""
    monkeypatch.setattr(events, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def scenario():
        gen = events._stream(_FakeRequest())
        first = await gen.__anext__()
        assert first.startswith(":")

        queue = next(iter(party_events._subscribers))
        queue.put_nowait("changed")
        second = await gen.__anext__()
        assert second.startswith("event: parties-changed")
        await gen.aclose()

    asyncio.run(scenario())


def test_stream_unsubscribes_on_close(monkeypatch):
    """연결이 끊기면(aclose) 구독을 해제해야 한다 — 안 그러면 죽은 연결의 큐가 계속 쌓인다."""
    monkeypatch.setattr(events, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def scenario():
        gen = events._stream(_FakeRequest())
        assert len(party_events._subscribers) == 0
        await gen.__anext__()  # 첫 next() 호출 시점에 subscribe()가 실행된다
        assert len(party_events._subscribers) == 1
        await gen.aclose()
        assert len(party_events._subscribers) == 0

    asyncio.run(scenario())
