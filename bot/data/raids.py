"""
레이드 데이터 정의
- short_name : 타이틀에 표시되는 약칭
- difficulties : 난이도별 최소 레벨·인원 구성
  - min_level   : 최소 아이템 레벨
  - total_slots : 전체 인원
  - party_split : 파티 분리 방식 (None이면 단일 파티, 정수면 파티당 인원)
  - gates       : 관문 수
"""

RAIDS: dict[str, dict] = {
    # "에기르(1막)": {
    #     "short_name": "1막",
    #     "icon": "🔥",
    #     "category": "카제로스",
    #     "difficulties": {
    #         "노말": {"min_level": 1660, "total_slots": 8, "party_split": 4, "gates": 2},
    #         "하드": {"min_level": 1680, "total_slots": 8, "party_split": 4, "gates": 2},
    #     },
    # },
    # "아브렐슈드(2막)": {
    #     "short_name": "2막",
    #     "icon": "🌑",
    #     "category": "카제로스",
    #     "difficulties": {
    #         "노말": {"min_level": 1670, "total_slots": 8, "party_split": 4, "gates": 2},
    #         "하드": {"min_level": 1690, "total_slots": 8, "party_split": 4, "gates": 2},
    #     },
    # },
    # "모르둠(3막)": {
    #     "short_name": "3막",
    #     "icon": "⚡",
    #     "category": "카제로스",
    #     "difficulties": {
    #         "노말": {"min_level": 1680, "total_slots": 8, "party_split": 4, "gates": 3},
    #         "하드": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 3},
    #     },
    # },
    "아르모체(4막)": {
        "short_name": "4막",
        "icon": "🗡️",
        "category": "카제로스",
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2},
            "하드": {"min_level": 1720, "total_slots": 8, "party_split": 4, "gates": 2},
        },
    },
    "종막": {
        "short_name": "종막",
        "icon": "🗡️",
        "category": "카제로스",
        "difficulties": {
            "노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2},
            "하드": {"min_level": 1730, "total_slots": 8, "party_split": 4, "gates": 2},
        },
    },
    "세르카": {
        "short_name": "세르카",
        "icon": "🗡️",
        "category": "그림자",
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 4, "party_split": None, "gates": 2},
            "하드": {"min_level": 1730, "total_slots": 4, "party_split": None, "gates": 2},
            "나이트메어": {"min_level": 1740, "total_slots": 4, "party_split": None, "gates": 2},
        },
    },
    "지평의 성당": {
        "short_name": "지평",
        "icon": "🔔",
        "category": "어비스",
        "difficulties": {
            "1단계": {"min_level": 1700, "total_slots": 4, "party_split": None, "gates": 2},
            "2단계": {"min_level": 1720, "total_slots": 4, "party_split": None, "gates": 2},
            "3단계": {"min_level": 1750, "total_slots": 4, "party_split": None, "gates": 2},
        },
    },
    # ── 신규 레이드 추가 예시 (아래 형식으로 추가) ──────────────────────────
    # "종막의문": {
    #     "short_name": "종막",
    #     "icon": "🌀",
    #     "category": "에픽",
    #     "difficulties": {
    #         "노말":       {"min_level": 1640, "total_slots": 8, "party_split": 4, "gates": 4},
    #         "하드":       {"min_level": 1660, "total_slots": 8, "party_split": 4, "gates": 4},
    #         "나이트메어": {"min_level": 1680, "total_slots": 8, "party_split": 4, "gates": 4},
    #     },
    # },
}

# 공격대 숙련도
PROFICIENCY: dict[str, str] = {
    "트라이":  "처음 도전하는 단계",
    "클경":    "클리어 경험 있음",
    "반숙":    "대부분의 패턴 숙지",
    "숙련":    "이 레이드를 완전 숙지",
}

# 서포터 직업 목록
SUPPORT_CLASSES: set[str] = {"바드", "홀리나이트", "도화가", "발키리"}

# 숫자 → 동그라미 숫자 (①~⑯)
CIRCLE_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧",
                  "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯"]


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
        for diff_name, diff_info in raid_info["difficulties"].items():
            if item_level >= diff_info["min_level"]:
                result.append((raid_name, diff_name, diff_info))
    return result
