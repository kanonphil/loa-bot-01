"""레이드 관리 인라인 수정(약칭/아이콘/수치/이름 변경 + 참조 건수 partial)과
레이드 체크 익스트림(원정대 주 1회) 섹션 + 메인 대시보드 익스트림 줄."""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import respx

from webapp import config, notification_store
from webapp.format import KST
from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal"
RAIDS_URL = f"{B}/raids"
CATEGORIES_URL = f"{B}/raid-categories"
CHARACTERS_URL = f"{B}/user-characters-grouped"
COMPLETIONS_URL = f"{B}/completions"
RAID_SELECTION_URL = f"{B}/raid-selection"
EXTREME_URL = f"{B}/completions/extreme"

CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}, {"name": "익스트림", "sort_order": 1, "is_extreme": 1}]
RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스", "is_extreme": False, "is_active": True,
        "is_pinned": False, "sort_order": 0, "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "카멘익스": {
        "short_name": "익스", "icon": "🔥", "category": "익스트림", "is_extreme": True, "is_active": True,
        "is_pinned": False, "sort_order": 0,
        "available_from": (datetime.now(KST) - timedelta(days=1)).isoformat(),
        "available_until": (datetime.now(KST) + timedelta(days=3)).isoformat(),
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 1},
            "하드": {"min_level": 1730, "total_slots": 8, "party_split": 4, "gates": 1},
        },
    },
}
CHARACTERS = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}]


def _admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    log_in(client, discord_id="111")


def _mock_admin_reads():
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))


# ── 관리자: 수정 폼 렌더 ────────────────────────────────────

def test_admin_tabs_render_edit_forms(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_admin_reads()
        cats = client.get("/admin/raids?tab=categories").text
        raids = client.get("/admin/raids?tab=raids").text
        diffs = client.get("/admin/raids?tab=difficulties&raid=카멘익스").text
    assert 'action="/admin/raids/categories/rename"' in cats
    assert 'action="/admin/raids/update"' in raids
    assert 'action="/admin/raids/rename"' in raids
    assert 'hx-get="/admin/raids/references?name=' in raids
    assert 'action="/admin/raids/difficulties/update"' in diffs
    assert 'action="/admin/raids/difficulties/rename"' in diffs
    assert 'value="1730"' in diffs
    assert "이미 개설된 공대에는 적용되지 않습니다" in diffs


def test_update_raid_forwards_and_redirects(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{B}/admin/raids/update").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/update", data={"name": "카멘익스", "short_name": " 익스2 ", "icon": ""})
    assert resp.status_code == 303 and resp.headers["location"] == "/admin/raids?tab=raids"
    assert json.loads(route.calls[0].request.content) == {"discord_id": "111", "name": "카멘익스", "short_name": "익스2", "icon": "⚔️"}


def test_rename_raid_success_renames_web_notification_filters(client, monkeypatch, notification_db):
    asyncio.run(notification_store.add_raid_filter("111", "카멘익스", None))
    asyncio.run(notification_store.add_raid_filter("111", "카멘익스", "하드"))
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{B}/admin/raids/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/rename", data={"old_name": "카멘익스", "new_name": "카멘 익스트림"})
    assert resp.status_code == 303
    prefs = asyncio.run(notification_store.get_preferences("111"))
    assert {f["raid_name"] for f in prefs["raid_filters"]} == {"카멘 익스트림"}


def test_rename_raid_failure_leaves_web_filters_and_shows_error(client, monkeypatch, notification_db):
    asyncio.run(notification_store.add_raid_filter("111", "카멘익스", None))
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{B}/admin/raids/rename").mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 같은 이름의 레이드가 있습니다."})
        )
        resp = client.post("/admin/raids/rename", data={"old_name": "카멘익스", "new_name": "아르모체(4막)"})
    assert resp.status_code == 303 and "error=" in resp.headers["location"]
    prefs = asyncio.run(notification_store.get_preferences("111"))
    assert prefs["raid_filters"][0]["raid_name"] == "카멘익스"


def test_rename_difficulty_renames_web_filter_but_keeps_all_difficulty_filter(client, monkeypatch, notification_db):
    asyncio.run(notification_store.add_raid_filter("111", "카멘익스", "노말"))
    asyncio.run(notification_store.add_raid_filter("222", "카멘익스", None))
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{B}/admin/difficulties/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/difficulties/rename",
                           data={"raid_name": "카멘익스", "old_difficulty": "노말", "new_difficulty": "일반"})
    assert resp.headers["location"] == "/admin/raids?tab=difficulties&raid=%EC%B9%B4%EB%A9%98%EC%9D%B5%EC%8A%A4"
    assert asyncio.run(notification_store.get_preferences("111"))["raid_filters"][0]["difficulty"] == "일반"
    assert asyncio.run(notification_store.get_preferences("222"))["raid_filters"][0]["difficulty"] is None


def test_update_difficulty_parses_blank_split_as_none(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{B}/admin/difficulties/update").mock(return_value=httpx.Response(200, json={"success": True}))
        client.post("/admin/raids/difficulties/update", data={
            "raid_name": "카멘익스", "difficulty": "노말", "min_level": "1710", "total_slots": "4", "party_split": "", "gates": "3",
        })
    payload = json.loads(route.calls[0].request.content)
    assert payload["party_split"] is None and payload["total_slots"] == 4 and payload["gates"] == 3


def test_rename_category_forwards(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{B}/admin/categories/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/categories/rename", data={"old_name": "카제로스", "new_name": "군단장"})
    assert resp.headers["location"] == "/admin/raids?tab=categories"
    assert json.loads(route.calls[0].request.content)["new_name"] == "군단장"


def test_references_partial_renders_counts(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/admin/raids/references").mock(return_value=httpx.Response(200, json={
            "parties_live": 1, "parties_all": 2, "party_history": 37, "raid_completions": 212,
            "raid_subscriptions": 4, "character_raid_selection": 9, "notification_logs": 5,
        }))
        resp = client.get("/admin/raids/references?name=카멘익스")
        diff_resp = client.get("/admin/raids/references?name=카멘익스&difficulty=노말")
    assert "클리어 기록 212" in resp.text and "레이드 선택 9" in resp.text
    assert "레이드 선택" not in diff_resp.text  # 난이도 기준엔 레이드 선택이 없다


def test_admin_edit_routes_require_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")
        assert client.post("/admin/raids/update", data={"name": "x", "short_name": "y"}).status_code == 403
        assert client.get("/admin/raids/references?name=x").status_code == 403


# ── 레이드 체크: 익스트림 섹션 ────────────────────────────────

def _mock_raid_check(extreme_raids=None, completions=None):
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(COMPLETIONS_URL).mock(return_value=httpx.Response(200, json={"week_key": "w", "completions": completions or []}))
    respx.get(RAID_SELECTION_URL).mock(return_value=httpx.Response(200, json={"customized": False, "selected_raids": []}))
    respx.get(EXTREME_URL).mock(return_value=httpx.Response(200, json={"week_key": "w", "raids": extreme_raids or []}))


def test_raid_check_shows_extreme_section_with_eligible_characters_only(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check(extreme_raids=[{"raid_name": "카멘익스", "cleared": False, "character_name": None, "difficulty": None}])
        resp = client.get("/raid-check")
    body = resp.text
    assert 'id="extreme-section"' in body
    assert "원정대 주 1회" in body and "미클리어" in body
    assert body.count('hx-post="/raid-check/extreme/set"') == 2  # 노말·하드
    assert "입장 가능한 캐릭터 없음" in body  # 하드(1730)엔 1720 캐릭터가 못 들어감
    assert body.count('<option value="발키리"') == 1  # 노말에만
    # 캐릭터 카드에는 익스트림이 빠지고 분모도 일반 레이드만
    card = body.split('class="raid-card-grid"')[-1]
    assert "카멘익스" not in card and "0 / 1 완료" in body


def test_raid_check_extreme_cleared_state(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check(extreme_raids=[{"raid_name": "카멘익스", "cleared": True, "character_name": "발키리", "difficulty": "노말"}])
        resp = client.get("/raid-check")
    body = resp.text
    assert "is-cleared" in body and 'hx-post="/raid-check/extreme/clear"' in body
    assert "발키리" in body.split('id="extreme-section"')[1].split("</section>")[0]
    assert 'hx-post="/raid-check/extreme/set"' not in body


def test_raid_check_hides_extreme_section_when_none_live(client):
    raids = {k: v for k, v in RAIDS.items() if k != "카멘익스"}
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=raids))
        resp = client.get("/raid-check")
    assert "원정대 주 1회" not in resp.text


def test_extreme_set_forwards_and_returns_section_with_toast(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check(extreme_raids=[{"raid_name": "카멘익스", "cleared": True, "character_name": "발키리", "difficulty": "노말"}])
        route = respx.post(f"{B}/completions/extreme/set").mock(
            return_value=httpx.Response(200, json={"success": True, "character_name": "발키리", "difficulty": "노말"})
        )
        resp = client.post("/raid-check/extreme/set", data={"raid_name": "카멘익스", "difficulty": "노말", "character_name": "발키리"})
    assert resp.status_code == 200
    assert json.loads(route.calls[0].request.content) == {"discord_id": "111", "raid_name": "카멘익스", "difficulty": "노말", "character_name": "발키리"}
    from urllib.parse import unquote
    assert unquote(resp.headers["X-Toast"]) == "익스 노말 원정대 클리어 — 발키리"
    assert 'id="extreme-section"' in resp.text and "<html" not in resp.text


def test_extreme_set_rejects_other_users_character(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        route = respx.post(f"{B}/completions/extreme/set").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/raid-check/extreme/set", data={"raid_name": "카멘익스", "difficulty": "노말", "character_name": "남의캐릭"})
    assert resp.status_code == 403 and not route.called


def test_extreme_clear_forwards(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        route = respx.post(f"{B}/completions/extreme/clear").mock(return_value=httpx.Response(200, json={"success": True, "removed": 1}))
        resp = client.post("/raid-check/extreme/clear", data={"raid_name": "카멘익스"})
    assert resp.status_code == 200 and route.called
    assert resp.headers["X-Toast-Type"] == "info"


def test_raid_select_page_has_no_extreme_option(client):
    with respx.mock:
        log_in(client)
        _mock_raid_check()
        resp = client.get("/raid-check/select/발키리")
    assert "카멘익스" not in resp.text and "아르모체(4막)" in resp.text


# ── 메인: 익스트림 줄 ──────────────────────────────────────

def test_dashboard_shows_extreme_line(client):
    progress = {"week_key": "w", "done": 0, "total": 1, "characters": [],
                "extreme": [{"raid_name": "카멘익스", "short_name": "익스", "cleared": True, "character_name": "발키리", "difficulty": "하드"}]}
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-characters").mock(return_value=httpx.Response(200, json=CHARACTERS))
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/raid-progress").mock(return_value=httpx.Response(200, json=progress))
        respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/main")
    assert "익스 · 발키리 · 하드" in resp.text
    assert "익스트림 · 원정대 주 1회" in resp.text
