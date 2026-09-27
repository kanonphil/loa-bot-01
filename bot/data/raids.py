"""
레이드 / 직업 데이터 — DB 기반 캐시.

RAIDS, SUPPORT_CLASSES 는 봇 시작 시 reload() 로 채워진다.
임포트한 코드는 dict/set 를 직접 참조하므로
reload() 가 in-place 로 갱신하면 재임포트 없이 최신 상태가 유지된다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ── 모듈 레벨 캐시 (in-place 갱신 필수) ──────────────────
RAIDS: dict = {}
SUPPORT_CLASSES: set = set()

KST = timezone(timedelta(hours=9))

# ── 정적 데이터 ──────────────────────────────────────────
PROFICIENCY: dict[str, str] = {
    "트라이": "처음 도전하는 단계",
    "클경":   "클리어 경험 있음",
    "반숙":   "대부분의 패턴 숙지",
    "숙련":   "이 레이드를 완전 숙지",
}

CIRCLE_NUMBERS = [
    "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧",
    "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯",
]


async def reload() -> None:
    """DB 에서 RAIDS 와 SUPPORT_CLASSES 를 읽어 캐시를 갱신한다."""
    import bot.database.manager as db
    new_raids = await db.get_raids_dict()
    new_support = await db.get_support_classes_set()
    RAIDS.clear()
    RAIDS.update(new_raids)
    SUPPORT_CLASSES.clear()
    SUPPORT_CLASSES.update(new_support)


# ── 헬퍼 함수 (기존 인터페이스 유지) ────────────────────

def get_raid(name: str) -> dict | None:
    return RAIDS.get(name)


def get_difficulty_info(raid_name: str, difficulty: str) -> dict | None:
    raid = RAIDS.get(raid_name)
    if raid:
        return raid["difficulties"].get(difficulty)
    return None


def _parse_aware(value: str | None) -> datetime | None:
    """운영 기간 문자열 → aware datetime. 비어 있거나 파싱 불가면 None.
    naive로 저장된 값(관리자 앱 구버전 등)은 KST로 간주 — aware와 비교하다 TypeError로
    500이 나지 않게 한다."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt


def is_extreme_available(raid_info: dict, now: datetime | None = None) -> bool:
    """익스트림 레이드가 지금 운영 중인지 — 활성 + available_from ≤ now ≤ available_until
    (양쪽 경계는 각각 없을 수 있다)."""
    if not raid_info.get("is_active", True):
        return False
    now = now or datetime.now(KST)
    start = _parse_aware(raid_info.get("available_from"))
    end = _parse_aware(raid_info.get("available_until"))
    if start and now < start:
        return False
    if end and end < now:
        return False
    return True


def is_recruitable(raid_info: dict) -> bool:
    """모집 목록에 띄울 레이드인지 — 비활성이거나 익스트림 기간이 지났으면 뺀다."""
    if not raid_info.get("is_active", True):
        return False
    if raid_info.get("is_extreme"):
        end = _parse_aware(raid_info.get("available_until"))
        if end and end < datetime.now(KST):
            return False
    return True


def recruit_order(raids: dict | None = None) -> list[tuple[str, dict]]:
    """공대 모집에서 보여줄 레이드를 표시 순서대로 반환한다.

    RAIDS 자체는 카테고리 → sort_order 순으로 정렬돼 있고, 여기서 상단 고정만
    앞으로 끌어올린다. 고정을 RAIDS 정렬에 섞지 않는 이유는 레이드 체크처럼
    카테고리 순서를 그대로 써야 하는 화면이 따로 있기 때문."""
    source = RAIDS if raids is None else raids
    items = [(name, info) for name, info in source.items() if is_recruitable(info)]
    return (
        [x for x in items if x[1].get("is_pinned")]
        + [x for x in items if not x[1].get("is_pinned")]
    )


def get_applicable_raids(item_level: float, include_extreme: bool = False) -> list[tuple[str, str, dict]]:
    """캐릭터가 입장 가능한 (레이드, 난이도, 난이도정보) 목록 — 캐릭터 단위 레이드 체크용.

    익스트림은 원정대당 주 1회라 캐릭터 카드에 넣으면 캐릭터 수만큼 못 채우는 칸이
    생기므로 기본 제외한다(원정대 단위 상태는 active_extreme_raids로 따로 다룬다)."""
    now = datetime.now(KST)
    result = []
    for raid_name, raid_info in RAIDS.items():
        if not raid_info.get("is_active", True):
            continue
        if raid_info.get("is_extreme"):
            if not include_extreme or not is_extreme_available(raid_info, now):
                continue
        for diff_name, diff_info in raid_info["difficulties"].items():
            if item_level >= diff_info["min_level"]:
                result.append((raid_name, diff_name, diff_info))
    return result


def active_extreme_raids(now: datetime | None = None) -> list[tuple[str, dict]]:
    """지금 운영 중인 익스트림 레이드 — RAIDS 순서 유지."""
    now = now or datetime.now(KST)
    return [
        (name, info) for name, info in RAIDS.items()
        if info.get("is_extreme") and is_extreme_available(info, now)
    ]
