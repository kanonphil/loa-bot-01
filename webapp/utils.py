"""여러 라우트가 공유하는 자잘한 헬퍼."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

KST = timezone(timedelta(hours=9))


def _parse_utc(value) -> datetime | None:
    """ISO 문자열(또는 datetime)을 시간대 있는 datetime으로. 시간대 표기가 없으면 UTC로 본다 —
    SQLite CURRENT_TIMESTAMP("2026-11-18 05:00:00")가 UTC 기준 시각이라서."""
    if isinstance(value, datetime):
        moment = value
    else:
        if not value:
            return None
        try:
            moment = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def ilvl(value, empty: str = "—") -> str:
    """아이템 레벨 — 게임과 같이 소수 둘째 자리까지("1735.00"). 숫자가 아니면 empty."""
    n = _number(value)
    return empty if n is None else f"{n:.2f}"


def combat_power(value, empty: str = "—") -> str:
    """전투력 — 천 단위 쉼표 + 소수 둘째 자리("2,812.45"). 숫자가 아니면 empty."""
    n = _number(value)
    return empty if n is None else f"{n:,.2f}"


def time_ago(iso: str | None) -> str:
    """ISO 시각을 "방금 전 / N분 전 / N시간 전 / N일 전" 상대 표기로 변환.
    파싱 실패(예상 못한 포맷)나 값 없음이면 빈 문자열."""
    moment = _parse_utc(iso)
    if moment is None:
        return ""
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"
    return f"{int(seconds // 86400)}일 전"


def kst_time(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC(또는 시간대 표기 있는) 시각을 한국 시간 문자열로. title 속성 등에 쓴다.
    값이 없거나 파싱 못 하면 빈 문자열."""
    moment = _parse_utc(value)
    return moment.astimezone(KST).strftime(fmt) if moment else ""


def safe_local_path(target: str | None, default: str = "/") -> str:
    r"""사용자가 넘긴 이동 경로가 이 사이트 안의 경로일 때만 돌려주고, 아니면 default.
    `//evil.com`, `/\evil.com`(브라우저가 `\`를 `/`로 바꿈), `https://…`, 제어문자가 섞인 값을 막는다."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return default
    if "\\" in target or any(ord(ch) < 32 for ch in target):
        return default
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return default
    return target
