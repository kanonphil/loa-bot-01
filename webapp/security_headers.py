"""보안 헤더 — 모든 응답에 붙이는 브라우저 방어선.

- HTML: Content-Security-Policy(스크립트는 이 사이트 파일 + 요청마다 바뀌는 nonce가 붙은 인라인만),
  Cache-Control: no-store(로그아웃·관리자 해제 뒤 뒤로가기로 예전 화면이 다시 보이던 문제).
- 전체: nosniff, 다른 사이트 iframe 금지, Referrer-Policy, Permissions-Policy, HSTS.

인라인 <script>는 반드시 nonce="{{ request.state.csp_nonce }}"를 붙인다. onclick="" 같은 인라인
이벤트 속성, javascript: 링크, hx-on은 CSP에 막히므로 쓰지 않는다(static/ui.js의 data-auto-submit·
data-history-back 등 위임 처리 사용). 정적 파일 캐시는 VersionedStaticFiles가 따로 정한다."""
import secrets

# Cloudflare Web Analytics 비콘 — Cloudflare가 HTML 끝에 <script src=static.cloudflareinsights.com>을 넣는다.
CSP_TEMPLATE = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}' https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' https://cloudflareinsights.com; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)

COMMON_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"strict-transport-security", b"max-age=31536000"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        is_static = scope["path"].startswith("/static/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in COMMON_HEADERS if k not in present]
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html") and not is_static:
                    headers = [(k, v) for k, v in headers if k.lower() not in (b"cache-control", b"content-security-policy")]
                    headers.append((b"cache-control", b"no-store, private"))
                    headers.append((b"content-security-policy", CSP_TEMPLATE.format(nonce=nonce).encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
