"""게시판 본문(리치 텍스트) HTML 정제 — contenteditable 에디터가 만들어낸 HTML을
저장 전에 화이트리스트로 걸러 저장형 XSS를 막는다."""
import bleach

_ALLOWED_TAGS = ["p", "br", "b", "strong", "i", "em", "u", "a", "img", "ul", "ol", "li", "blockquote"]
_ALLOWED_ATTRS = {"a": ["href", "target", "rel"], "img": ["src", "alt"]}
_ALLOWED_PROTOCOLS = ["http", "https"]


def clean_html(html: str) -> str:
    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
