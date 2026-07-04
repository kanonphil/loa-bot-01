"""레이드 체크 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
CATEGORIES_URL = "http://bot-server.internal/api/internal/raid-categories"
COMPLETIONS_URL = "http://bot-server.internal/api/internal/completions"
TOGGLE_URL = "http://bot-server.internal/api/internal/completions/toggle"
CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막",
        "icon": "🗡️",
        "category": "카제로스",
        "is_extreme": False,
        "is_active": True,
        "available_from": None,
        "available_until": None,
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2},
        },
    },
}

# 난이도가 2개인 레이드 — "레이드 단위" 진행률 계산 검증용
RAIDS_MULTI_DIFF = {
    "종막": {
        "short_name": "종막", "icon": "⚔️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {
            "노말": {"min_level": 1690, "total_slots": 8, "party_split": 4, "gates": 3},
            "하드": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 3},
        },
    },
}
CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}]
CHARACTERS = [{"character_name": "발키리", "character_class": "서포터", "item_level": 1720.0}]


def _mock_common(completions=None):
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(COMPLETIONS_URL).mock(
        return_value=httpx.Response(
            200, json={"week_key": "2026-01-07", "completions": completions or []}
        )
    )


def test_no_characters_shows_registration_notice(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "/api등록" in resp.text


def test_raid_check_page_renders_checklist(client):
    with respx.mock:
        log_in(client)
        _mock_common()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    body = resp.text
    assert "발키리" in body
    assert "카제로스" in body
    assert "4막" in body
    assert "0 / 1 완료" in body


def test_raid_check_page_shows_done_state(client):
    with respx.mock:
        log_in(client)
        _mock_common(completions=["아르모체(4막)_노말"])
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "1 / 1 완료" in resp.text


def test_toggle_calls_bot_and_returns_updated_fragment(client):
    with respx.mock:
        log_in(client)
        _mock_common()
        toggle_route = respx.post(TOGGLE_URL).mock(
            return_value=httpx.Response(200, json={"completed": True})
        )
        # 토글 이후 재조회 시에는 완료된 상태로 응답
        respx.get(COMPLETIONS_URL).mock(
            return_value=httpx.Response(
                200, json={"week_key": "2026-01-07", "completions": ["아르모체(4막)_노말"]}
            )
        )

        resp = client.post(
            "/raid-check/toggle",
            data={"raid_name": "아르모체(4막)", "difficulty": "노말", "character_name": "발키리"},
        )

    assert resp.status_code == 200
    assert toggle_route.called
    assert "1 / 1 완료" in resp.text


def test_toggle_rejects_character_not_owned_by_user(client):
    with respx.mock:
        log_in(client)
        _mock_common()
        toggle_route = respx.post(TOGGLE_URL).mock(
            return_value=httpx.Response(200, json={"completed": True})
        )

        resp = client.post(
            "/raid-check/toggle",
            data={"raid_name": "아르모체(4막)", "difficulty": "노말", "character_name": "남의캐릭터"},
        )

    assert resp.status_code == 403
    assert not toggle_route.called  # 봇 API가 아예 호출되지 않아야 함


def test_progress_counts_by_raid_not_difficulty(client):
    """레이드 하나에 난이도가 2개 있어도 분모는 1이어야 하고(레이드 단위),
    그 중 하나만 완료해도 그 레이드는 완료로 잡혀야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS_MULTI_DIFF))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(
            return_value=httpx.Response(
                200, json={"week_key": "2026-01-07", "completions": ["종막_하드"]}
            )
        )
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "1 / 1 완료" in resp.text  # 2/2가 아니라 1/1 — 레이드 단위 집계


def test_raid_check_requires_login(client):
    resp = client.get("/raid-check")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"
