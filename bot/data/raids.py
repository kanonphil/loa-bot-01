"""
레이드 / 직업 데이터 — DB 기반 캐시.

RAIDS, SUPPORT_CLASSES 는 봇 시작 시 reload() 로 채워진다.
임포트한 코드는 dict/set 를 직접 참조하므로
reload() 가 in-place 로 갱신하면 재임포트 없이 최신 상태가 유지된다.
"""
from __future__ import annotations

# ── 모듈 레벨 캐시 (in-place 갱신 필수) ──────────────────
RAIDS: dict = {}
SUPPORT_CLASSES: set = set()

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


def get_applicable_raids(item_level: float) -> list[tuple[str, str, dict]]:
    result = []
    for raid_name, raid_info in RAIDS.items():
        if not raid_info.get("is_active", True):
            continue
        for diff_name, diff_info in raid_info["difficulties"].items():
            if item_level >= diff_info["min_level"]:
                result.append((raid_name, diff_name, diff_info))
    return result
