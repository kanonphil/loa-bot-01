"""원본 응답 gzip — Cloudflare→원본 구간이 느릴 때 전송량을 줄이기 위한 완화.
SSE 스트림은 압축되면 이벤트가 버퍼에 갇히므로 제외돼야 한다."""
import respx

from webapp.tests.conftest import log_in


def test_large_html_is_gzipped(client):
    import httpx

    with respx.mock:
        log_in(client, discord_id="111")
        respx.get("http://bot-server.internal/api/internal/parties").mock(return_value=httpx.Response(200, json=[]))
        respx.get("http://bot-server.internal/api/internal/user-characters").mock(return_value=httpx.Response(200, json=[]))
        respx.get("http://bot-server.internal/api/internal/raids").mock(return_value=httpx.Response(200, json={}))
        resp = client.get("/parties", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert "공대" in resp.text  # httpx가 투명하게 풀어준다


def test_static_css_is_gzipped(client):
    resp = client.get("/static/style.css", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


def test_tiny_response_not_gzipped(client):
    resp = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


def test_event_stream_not_gzipped(client, monkeypatch):
    import webapp.routes.events as events

    async def fake_stream(request):
        yield ": keep-alive\n\n"

    monkeypatch.setattr(events, "_stream", fake_stream)
    with respx.mock:
        log_in(client, discord_id="111")
        with client.stream("GET", "/events/parties", headers={"Accept-Encoding": "gzip"}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in resp.headers
