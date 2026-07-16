"""여러 라우트가 공유하는 자잘한 헬퍼."""
from datetime import datetime, timezone


def time_ago(iso: str | None) -> str:
    """ISO 시각을 "방금 전 / N분 전 / N시간 전 / N일 전" 상대 표기로 변환.
    파싱 실패(예상 못한 포맷)나 값 없음이면 빈 문자열."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"
    return f"{int(seconds // 86400)}일 전"
