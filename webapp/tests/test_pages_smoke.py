"""모든 페이지가 실제로 렌더되는지 확인하는 스모크 테스트.

라우트별 테스트는 그 화면의 규칙을 보지만, 공용 매크로(_ui.html)나 base.html을
건드리면 "그 화면은 안 봤는데 같이 깨지는" 일이 생긴다. 여기서는 내용이 아니라
"데이터가 비어 있어도 500이 안 난다"만 전 페이지에 대해 확인한다.
"""
import httpx
import pytest
import respx

from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal"

EMPTY_PROGRESS = {"week_key": "2026-01-07", "done": 0, "total": 0, "characters": []}
RAIDS = {
    "종막": {
        "short_name": "종막", "icon": "⚔️", "category": "카제로스",
        "is_extreme": False, "is_active": True, "is_pinned": True,
        "available_from": None, "available_until": None, "sort_order": 0,
        "difficulties": {"노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    # 난이도를 아직 안 붙인 레이드 — 선택기가 여기서 죽으면 안 된다
    "난이도미등록": {
        "short_name": "미등록", "icon": "🆕", "category": "카제로스",
        "is_extreme": False, "is_active": True, "is_pinned": False,
        "available_from": None, "available_until": None, "sort_order": 1,
        "difficulties": {},
    },
}

PAGES = [
    "/main",
    "/parties",
    "/parties?filter=recruiting",
    "/parties?filter=mine",
    "/parties?filter=eligible",
    "/parties/create",
    "/expedition",
    "/raid-check",
    "/ranking",
    "/ranking?metric=weekly_clears",
    "/ranking?metric=item_level",
    "/calendar",
    "/calendar?view=week",
    "/settings",
    "/tools/auction-calculator",
]


def _mock_everything():
    respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/parties/calendar").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/parties/proficiency-options").mock(
        return_value=httpx.Response(200, json=[{"value": "숙련", "label": "숙련", "description": "d"}])
    )
    respx.get(f"{B}/raid-progress").mock(return_value=httpx.Response(200, json=EMPTY_PROGRESS))
    respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(f"{B}/raid-categories").mock(
        return_value=httpx.Response(200, json=[{"name": "카제로스", "sort_order": 0, "is_extreme": 0}])
    )
    respx.get(f"{B}/raid-selection").mock(
        return_value=httpx.Response(200, json={"customized": False, "selected_raids": []})
    )
    respx.get(f"{B}/completions").mock(
        return_value=httpx.Response(200, json={"week_key": "2026-01-07", "completions": []})
    )
    respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/accounts/list").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/support-classes").mock(return_value=httpx.Response(200, json=["바드"]))
    respx.get(f"{B}/ranking").mock(
        return_value=httpx.Response(200, json={"metric": "combat_power", "role": "dps", "entries": []})
    )


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_with_empty_data(client, path):
    with respx.mock:
        log_in(client)
        _mock_everything()
        resp = client.get(path)

    assert resp.status_code == 200, f"{path} → {resp.status_code}"
    body = resp.text
    # Jinja가 조용히 삼킨 오류 흔적이 본문에 찍히는 경우를 잡는다
    assert "UndefinedError" not in body
    assert "jinja2.exceptions" not in body


def test_raid_picker_survives_raid_without_difficulty(client):
    """난이도가 없는 레이드가 섞여 있어도 공대 개설 화면은 떠야 한다."""
    with respx.mock:
        log_in(client)
        _mock_everything()
        resp = client.get("/parties/create")

    assert resp.status_code == 200
    assert "난이도 미등록" in resp.text


def test_pinned_raid_is_listed_first_in_picker(client):
    with respx.mock:
        log_in(client)
        _mock_everything()
        resp = client.get("/parties/create")

    body = resp.text
    assert body.index("자주 여는 레이드") < body.index("카제로스")
