"""레이드 체크 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in, without_toast

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
CATEGORIES_URL = "http://bot-server.internal/api/internal/raid-categories"
COMPLETIONS_URL = "http://bot-server.internal/api/internal/completions"
TOGGLE_URL = "http://bot-server.internal/api/internal/completions/toggle"
CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters-grouped"
RAID_SELECTION_URL = "http://bot-server.internal/api/internal/raid-selection"

NOT_CUSTOMIZED = {"customized": False, "selected_raids": []}


def _mock_not_customized():
    respx.get(RAID_SELECTION_URL).mock(return_value=httpx.Response(200, json=NOT_CUSTOMIZED))

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
    _mock_not_customized()
    respx.get("http://bot-server.internal/api/internal/completions/extreme").mock(
        return_value=httpx.Response(200, json={"week_key": "2026-01-07", "raids": []})
    )










def test_toggle_rejects_character_not_owned_by_user(client):
    with respx.mock:
        log_in(client)
        _mock_common()
        toggle_route = respx.post(TOGGLE_URL).mock(
            return_value=httpx.Response(200, json={"completed": True})
        )

        resp = client.post(
            "/raid-check/toggle",
            data={
                "raid_name": "아르모체(4막)", "difficulty": "노말",
                "character_name": "남의캐릭터", "card_index": "0",
            },
        )

    assert resp.status_code == 403
    assert not toggle_route.called  # 봇 API가 아예 호출되지 않아야 함






TWO_CHARACTERS = [
    {"character_name": "발키리", "character_class": "서포터", "item_level": 1720.0, "account_label": "발키리"},
    {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1700.0, "account_label": "발키리"},
]

TWO_ACCOUNT_CHARACTERS = [
    {"character_name": "발키리", "character_class": "서포터", "item_level": 1720.0, "account_label": "발키리"},
    {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1700.0, "account_label": "발키리"},
    {"character_name": "슬레이어", "character_class": "슬레이어", "item_level": 1690.0, "account_label": "슬레이어부계정"},
]


def _completions_by_character(character_completions: dict[str, list[str]]):
    def _side_effect(request):
        character_name = request.url.params["character_name"]
        return httpx.Response(
            200,
            json={"week_key": "2026-01-07", "completions": character_completions.get(character_name, [])},
        )

    return _side_effect












# 레이드가 늘어날 때를 대비한 "캐릭터별 레이드 선택" 검증용 — 같은 카테고리에 레이드 2개.
RAIDS_TWO = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True, "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "카멘": {
        "short_name": "카멘", "icon": "🔥", "category": "카제로스",
        "is_extreme": False, "is_active": True, "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1580, "total_slots": 8, "party_split": 4, "gates": 3}},
    },
}






def test_raid_select_page_defaults_all_checked_when_never_customized(client):
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS_TWO))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        _mock_not_customized()
        resp = client.get("/raid-check/select/발키리")

    assert resp.status_code == 200
    assert 'value="아르모체(4막)" checked' in resp.text
    assert 'value="카멘" checked' in resp.text


def test_raid_select_page_prechecks_saved_selection(client):
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS_TWO))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        respx.get(RAID_SELECTION_URL).mock(
            return_value=httpx.Response(200, json={"customized": True, "selected_raids": ["카멘"]})
        )
        resp = client.get("/raid-check/select/발키리")

    assert resp.status_code == 200
    assert 'value="카멘" checked' in resp.text
    assert 'value="아르모체(4막)"' in resp.text  # 체크박스 자체는 여전히 목록에 있어야 함
    assert 'value="아르모체(4막)" checked' not in resp.text  # 다만 선택 안 됐으니 체크는 안 되어 있어야 함


def test_raid_select_page_rejects_other_users_character(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        resp = client.get("/raid-check/select/남의캐릭터")

    assert resp.status_code == 403


def test_raid_select_save_calls_bot_and_redirects(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        save_route = respx.post(RAID_SELECTION_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        resp = client.post(
            "/raid-check/select/발키리",
            data={"raid_names": ["카멘"]},
        )

    assert resp.status_code in (302, 303, 307)
    assert without_toast(resp.headers["location"]) == "/main"
    assert "toast=" in resp.headers["location"]  # 저장 토스트
    assert save_route.called


def test_raid_select_save_rejects_other_users_character(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        save_route = respx.post(RAID_SELECTION_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        resp = client.post(
            "/raid-check/select/남의캐릭터",
            data={"raid_names": ["카멘"]},
        )

    assert resp.status_code == 403
    assert not save_route.called
