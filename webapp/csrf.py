"""CSRF 방어 — Origin/Referer 검사 미들웨어.

토큰 방식 대신 헤더 검사를 쓴다: 세션 쿠키가 SameSite=Lax이고 Domain=.dmlj-loa.online이라
같은 사이트의 다른 서브도메인에서 보낸 POST에는 쿠키가 실리기 때문에 Lax만으로는 부족하다.

규칙(POST/PUT/PATCH/DELETE에만 적용):
  1. Origin 헤더가 있으면 그 호스트가 "이 요청의 Host" 또는 DISCORD_REDIRECT_URI의 호스트일 때만 통과.
     (브라우저는 교차 출처·폼 POST에 항상 Origin을 보낸다. "null"도 거부.)
  2. Origin이 없으면 Referer로 같은 판정.
  3. 둘 다 없으면 거부(표준 관행 — 정상 브라우저 폼 제출은 둘 중 하나는 반드시 보낸다).
GET/HEAD/OPTIONS는 상태를 바꾸지 않으므로 검사하지 않는다.
"""
from urllib.parse import urlparse

from starlette.responses import PlainTextResponse

from webapp import config

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _netloc(value: str) -> str:
    try:
        return urlparse(value).netloc.lower()
    except ValueError:
        return ""


class OriginCheckMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        allowed = {_netloc(config.DISCORD_REDIRECT_URI)}
        if headers.get("host"):
            allowed.add(headers["host"].lower())
        allowed.discard("")

        origin = headers.get("origin")
        referer = headers.get("referer")
        source = origin if origin is not None else referer
        if not source or _netloc(source) not in allowed:
            response = PlainTextResponse("허용되지 않는 요청입니다. 페이지를 새로고침한 뒤 다시 시도해주세요.", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
