"""관리자 탭(/admin/raids) — 노출 여부와 CRUD 폼 제출 검증. 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
CATEGORIES_URL = "http://bot-server.internal/api/internal/raid-categories"
JOB_CLASSES_URL = "http://bot-server.internal/api/internal/job-classes"
ADD_CATEGORY_URL = "http://bot-server.internal/api/internal/admin/categories/add"
PARTIES_URL = "http://bot-server.internal/api/internal/parties"
USER_CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"

CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": False}]
RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스", "is_extreme": False,
        "is_active": True, "is_pinned": False, "available_from": None, "available_until": None,
        "sort_order": 0,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}
JOB_CLASSES = [{"name": "워로드", "is_support": 0}, {"name": "홀리나이트", "is_support": 1}]


def _mock_reads():
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(JOB_CLASSES_URL).mock(return_value=httpx.Response(200, json=JOB_CLASSES))


def test_non_admin_gets_403(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999-someone-else"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/admin/raids")
    assert resp.status_code == 403


def test_non_admin_does_not_see_admin_nav(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999-someone-else"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/parties")
    assert "레이드 관리" not in resp.text


def test_admin_sees_nav_and_page(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        nav_resp = client.get("/parties")
        _mock_reads()
        page_resp = client.get("/admin/raids")

    assert "레이드 관리" in nav_resp.text
    assert page_resp.status_code == 200
    assert "아르모체(4막)" in page_resp.text  # 기본 탭(레이드)


def test_classes_tab_shows_job_classes(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        _mock_reads()
        resp = client.get("/admin/raids?tab=classes")
    assert "홀리나이트" in resp.text
    assert "아르모체(4막)" not in resp.text  # 다른 탭 내용은 안 보임


def test_raid_row_links_to_difficulties_tab(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        _mock_reads()
        resp = client.get("/admin/raids?tab=raids")
    assert "tab=difficulties&amp;raid=" in resp.text


def test_add_category_forwards_discord_id_and_redirects(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.post(ADD_CATEGORY_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        resp = client.post(
            "/admin/raids/categories/add",
            data={"name": "새카테고리", "sort_order": "1"},
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/raids?tab=categories"
    import json as _json

    body = _json.loads(route.calls[0].request.content)
    assert body == {"discord_id": "111", "name": "새카테고리", "sort_order": 1}


def test_add_category_failure_redirects_with_error(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(ADD_CATEGORY_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "관리자 권한이 없습니다."})
        )
        resp = client.post(
            "/admin/raids/categories/add",
            data={"name": "새카테고리", "sort_order": "1"},
        )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
