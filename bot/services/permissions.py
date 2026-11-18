"""관리자 여부 검증 — 웹앱 내부 API(bot/api/routes/internal.py)와 디스코드/공용 코어
(bot/ui/views.py)가 같은 함수를 쓴다(예전엔 두 곳에 똑같은 함수가 따로 있었다)."""
import config


def require_admin(discord_id: str) -> str | None:
    """discord_id가 ADMIN_DISCORD_IDS에 없으면 에러 사유 문자열, 문제없으면 None.
    X-Webapp-Key는 웹앱 전체를 인증할 뿐 관리자 여부를 모르므로, 관리자 전용 액션은
    매 요청마다 여기서 다시 검증한다(웹앱 세션 쪽 검사만 믿지 않는다)."""
    if discord_id not in config.ADMIN_DISCORD_IDS:
        return "관리자 권한이 없습니다."
    return None
