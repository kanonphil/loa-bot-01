"""요청 본문 크기 상한 — 수 MB짜리 폼을 보내 저장소·메모리를 채우는 것을 막는다.

Content-Length가 상한을 넘으면 바로 413, 헤더 없이 스트리밍으로 보내도 읽는 도중 상한을 넘으면 413.
이 사이트의 폼은 전부 몇 KB 안쪽이다(가장 큰 것도 관리자 순서 저장 JSON)."""
from starlette.responses import PlainTextResponse

MAX_BODY_BYTES = 64 * 1024


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        return await _too_large()(scope, receive, send)
                except ValueError:
                    return await PlainTextResponse("Bad Request", status_code=400)(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _too_large()(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


def _too_large():
    return PlainTextResponse("요청 내용이 너무 큽니다.", status_code=413)
