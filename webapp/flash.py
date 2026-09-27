"""POST 뒤 redirect에 실어 보내는 1회성 토스트.

이전엔 화면마다 `?saved=`, `?error=`, `?join_error=` 같은 파라미터를 따로 정하고 템플릿마다
`.flash-data` 분기를 늘려 갔다. 이제 `?toast=<문구>&toast_type=success|error|info` 하나로 통일하고
base.html이 모든 페이지에서 한 번에 토스트로 바꿔 띄운다(toast.js가 표시 후 URL에서 지운다).

POST 핸들러가 페이지를 직접 렌더하면 뒤로가기가 POST 응답으로 돌아가고 F5가 동작을 재실행한다
(원정대 동기화 20초 API가 다시 돌거나 공대가 두 번 만들어진다) — 그래서 모든 POST는 이 헬퍼로
redirect 한다.
"""
from urllib.parse import quote

from starlette.responses import RedirectResponse

DEFAULT_FAILURE = "처리하지 못했습니다. 잠시 후 다시 시도해주세요."


def with_toast(path: str, message: str, kind: str = "success") -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}toast={quote(message)}&toast_type={kind}"


def redirect_with_toast(path: str, message: str | None = None, kind: str = "success") -> RedirectResponse:
    """message가 없으면 토스트 없이 그냥 redirect."""
    return RedirectResponse(with_toast(path, message, kind) if message else path, status_code=303)


def redirect_result(path: str, result: dict, success_message: str | None, fallback: str = DEFAULT_FAILURE) -> RedirectResponse:
    """봇 API의 {"success", "reason"} 응답을 토스트로 — 실패 사유가 비어 있어도 조용히 넘어가지 않는다."""
    if not result.get("success"):
        return redirect_with_toast(path, result.get("reason") or fallback, "error")
    return redirect_with_toast(path, success_message)
