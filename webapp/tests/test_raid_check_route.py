"""레이드 체크 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

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
            data={
                "raid_name": "아르모체(4막)", "difficulty": "노말",
                "character_name": "발키리", "card_index": "0",
            },
        )

    assert resp.status_code == 200
    assert toggle_route.called
    assert "1 / 1 완료" in resp.text
    assert 'id="raid-card-0"' in resp.text  # 토글 응답은 그 카드 하나만 다시 그려서 반환


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
        _mock_not_customized()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "1 / 1 완료" in resp.text  # 2/2가 아니라 1/1 — 레이드 단위 집계


def test_raid_check_requires_login(client):
    resp = client.get("/raid-check")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


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


def test_raid_check_shows_a_separate_card_per_character(client):
    """카드 그리드니까 캐릭터마다 카드가 하나씩, 각자 자기 완료 상태로 따로 보여야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(
            side_effect=_completions_by_character({"발키리": ["아르모체(4막)_노말"]})
        )
        _mock_not_customized()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "raid-card-grid" in resp.text
    assert 'id="raid-card-0"' in resp.text
    assert 'id="raid-card-1"' in resp.text
    assert "발키리" in resp.text
    assert "워로드부캐" in resp.text
    # 카드가 각자 다른 완료 상태를 가져야 한다 — 발키리는 1/1, 워로드부캐는 0/1
    assert "1 / 1 완료" in resp.text
    assert "0 / 1 완료" in resp.text


def test_toggle_only_updates_its_own_card_fragment(client):
    """토글 응답은 해당 캐릭터의 카드 하나만 담아야 하고, 다른 캐릭터 이름이 섞여 나오면 안 된다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_CHARACTERS))
        respx.post(TOGGLE_URL).mock(return_value=httpx.Response(200, json={"completed": True}))
        respx.get(COMPLETIONS_URL).mock(
            side_effect=_completions_by_character({"워로드부캐": ["아르모체(4막)_노말"]})
        )
        _mock_not_customized()

        resp = client.post(
            "/raid-check/toggle",
            data={
                "raid_name": "아르모체(4막)", "difficulty": "노말",
                "character_name": "워로드부캐", "card_index": "1",
            },
        )

    assert resp.status_code == 200
    assert 'id="raid-card-1"' in resp.text
    assert "워로드부캐" in resp.text
    assert "발키리" not in resp.text


def test_single_account_hides_account_tabs(client):
    """부계정이 없으면(계정 라벨이 하나뿐이면) 탭을 굳이 보여줄 필요가 없다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(side_effect=_completions_by_character({}))
        _mock_not_customized()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "account-tabs" not in resp.text


def test_multi_account_shows_tabs_and_defaults_to_all(client):
    """부계정이 여러 개면 탭이 뜨고, 기본값(쿼리 파라미터 없음)은 전체 표시."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_ACCOUNT_CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(side_effect=_completions_by_character({}))
        _mock_not_customized()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "account-tabs" in resp.text
    assert "발키리" in resp.text
    assert "슬레이어" in resp.text
    assert "슬레이어부계정" in resp.text
    assert "워로드부캐" in resp.text
    # 전체 탭이 활성 상태여야 한다
    assert '<a href="/raid-check" class="account-tab active">전체</a>' in resp.text


def test_selecting_account_filters_cards_to_that_account_only(client):
    """계정 탭을 골랐으면 그 계정 캐릭터 카드만 보이고 다른 계정 캐릭터는 안 보여야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_ACCOUNT_CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(side_effect=_completions_by_character({}))
        _mock_not_customized()
        resp = client.get("/raid-check", params={"account": "슬레이어부계정"})

    assert resp.status_code == 200
    assert 'id="raid-card-0"' in resp.text
    assert 'id="raid-card-1"' not in resp.text  # 카드가 하나만 렌더링돼야 함
    assert "워로드부캐" not in resp.text  # 다른 계정 캐릭터 이름은 카드에만 나오므로 이걸로 필터링 검증
    assert 'class="account-tab active">슬레이어부계정</a>' in resp.text


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


def test_card_shows_only_selected_raids_when_customized(client):
    """레이드 선택을 한 번이라도 저장했으면, 카드에는 그 레이드만 보여야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS_TWO))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json={"week_key": "2026-01-07", "completions": []})
        )
        respx.get(RAID_SELECTION_URL).mock(
            return_value=httpx.Response(200, json={"customized": True, "selected_raids": ["카멘"]})
        )
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "카멘" in resp.text
    assert "4막" not in resp.text  # 선택 안 한 아르모체(4막)는 카드에서 빠져야 함
    assert "0 / 1 완료" in resp.text  # 진행률도 선택된 1개 기준


def test_card_shows_all_applicable_raids_when_never_customized(client):
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS_TWO))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        respx.get(COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json={"week_key": "2026-01-07", "completions": []})
        )
        _mock_not_customized()
        resp = client.get("/raid-check")

    assert resp.status_code == 200
    assert "카멘" in resp.text
    assert "4막" in resp.text
    assert "0 / 2 완료" in resp.text


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
    assert resp.headers["location"] == "/raid-check"
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
