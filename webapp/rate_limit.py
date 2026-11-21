"""IP별 요청 횟수 제한 — 자동화 도구로 로그인·폼 제출·화면을 대량으로 두드리는 것을 막는다.

웹 서버 8080은 Cloudflare만 들어올 수 있으므로(서버 방화벽) 실제 접속자 IP는 CF-Connecting-IP 헤더를
믿는다. 프로세스 하나(uvicorn 워커 1개)라 메모리에 둔다 — 재시작하면 초기화돼도 문제없다.

한도는 길드원이 평소 쓰는 양의 몇 배로 넉넉히 잡았다(같은 PC방·공유기에서 여러 명이 써도 걸리지 않게).
실시간 연결(/events/*)·정적 파일·헬스 체크는 세지 않는다."""
import time
from collections import deque

from starlette.responses import HTMLResponse, PlainTextResponse

# (이름, 경로 판단, 창 길이(초), 허용 횟수)
RULES = [
    ("login", lambda method, path: path in ("/login", "/callback"), 60, 20),
    ("write", lambda method, path: method in ("POST", "PUT", "PATCH", "DELETE"), 60, 60),
    ("any", lambda method, path: True, 60, 300),
]
EXEMPT_PREFIXES = ("/static/", "/events/", "/health")
MAX_TRACKED_KEYS = 20000  # 무작위 IP로 메모리를 채우는 것 방지 — 넘으면 오래된 것부터 비운다

_hits: dict[tuple[str, str], deque] = {}


def reset() -> None:
    _hits.clear()


def client_ip(scope) -> str:
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    ip = headers.get(b"cf-connecting-ip") or b""
    if ip:
        return ip.decode("latin-1").strip()
    client = scope.get("client")
    return client[0] if client else "?"


def _check(key: tuple[str, str], window: int, limit: int, now: float) -> float | None:
    """한도를 넘으면 다시 시도할 수 있을 때까지 남은 초, 아니면 None(그리고 이번 요청을 센다)."""
    q = _hits.get(key)
    if q is None:
        if len(_hits) >= MAX_TRACKED_KEYS:
            for old in list(_hits)[: MAX_TRACKED_KEYS // 10]:
                _hits.pop(old, None)
        q = _hits[key] = deque()
    while q and q[0] <= now - window:
        q.popleft()
    if len(q) >= limit:
        return max(1.0, q[0] + window - now)
    q.append(now)
    return None


class RateLimitMiddleware:
    def __init__(self, app, enabled: bool = True):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http" or scope["path"].startswith(EXEMPT_PREFIXES):
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        ip = client_ip(scope)
        now = time.monotonic()
        for name, applies, window, limit in RULES:
            if not applies(method, path):
                continue
            wait = _check((name, ip), window, limit, now)
            if wait is not None:
                return await _too_many(scope, int(wait) + 1)(scope, receive, send)
        await self.app(scope, receive, send)


def _too_many(scope, retry_after: int):
    headers = {"Retry-After": str(retry_after)}
    accept = dict(scope.get("headers", [])).get(b"accept", b"")
    is_htmx = any(k.lower() == b"hx-request" for k, _ in scope.get("headers", []))
    if is_htmx or b"text/html" not in accept:
        return PlainTextResponse("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.", status_code=429, headers=headers)
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>잠시 후 다시 시도해주세요</title>"
        "<body style='font-family:sans-serif;background:#111318;color:#e8ebf1;display:grid;place-items:center;min-height:100vh;margin:0'>"
        f"<div style='text-align:center'><h1 style='font-size:20px'>요청이 너무 많습니다</h1>"
        f"<p style='color:#9aa3b2'>{retry_after}초 뒤에 다시 시도해주세요.</p></div>"
    )
    return HTMLResponse(body, status_code=429, headers=headers)
