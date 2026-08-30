"""웹 관리자의 "공대 관리" 기능 검증 — 파티 상세 페이지에서 관리자가 파티장 패널을
쓸 수 있는지, 클리어 되돌리기, /admin/parties 목록 페이지. 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
COMMENTS_URL = "http://bot-server.internal/api/internal/parties/p1/comments"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/p1/eligibility"
WAITLIST_STATUS_URL = "http://bot-server.internal/api/internal/parties/p1/waitlist-status"
INVITABLE_USERS_URL = "http://bot-server.internal/api/internal/parties/p1/invitable-users"
CLOSE_URL = "http://bot-server.internal/api/internal/parties/p1/close"
REVERT_URL = "http://bot-server.internal/api/internal/admin/parties/p1/revert-clear"
ADMIN_PARTIES_URL = "http://bot-server.internal/api/internal/admin/parties"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}

PARTY = {
    "message_id": "p1", "channel_id": "555", "guild_id": "test-guild-id",
    "leader_id": "111", "raid_name": "아르모체(4막)", "difficulty": "노말",
    "proficiency": "숙련", "scheduled_time": "05/20 20:00",
    "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [
        {"slot_number": 1, "discord_id": "111", "character_name": "리더캐릭",
         "character_class": "워로드", "role": "dps"},
    ],
}
DISBANDED_PARTY = {**PARTY, "status": "disbanded"}


# ── 파티 상세: 관리자가 파티장 없이 관리 패널을 쓸 수 있는지 ─────────

def test_admin_sees_leader_panel_on_party_they_do_not_lead(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")  # 파티원도 아니고 파티장도 아닌 관리자
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json={"can_join": False, "reason": "이미 마감된 공대입니다."}))
        respx.get(WAITLIST_STATUS_URL).mock(return_value=httpx.Response(200, json={"on_waitlist": False}))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "파티장 관리" in resp.text
    assert "관리자 권한으로 보는 중" in resp.text
    assert ">클리어<" in resp.text  # 클리어는 관리자도 씀(파티장이 놓친 경우 대응)
    assert "파티 취소" not in resp.text  # 취소는 아직 관리자 범위 밖 — 의도적으로 숨김


def test_admin_can_clear_party_via_leader_panel_route(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        clear_route = respx.post("http://bot-server.internal/api/internal/parties/p1/clear").mock(
            return_value=httpx.Response(200, json={"success": True, "cleared_count": 1})
        )
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=DISBANDED_PARTY))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/clear")

    assert resp.status_code == 303
    assert clear_route.called
    import json as _json
    assert _json.loads(clear_route.calls[0].request.content)["discord_id"] == "999"


def test_non_admin_outsider_does_not_see_leader_panel(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="555")  # 파티원도 아니고 관리자도 아님
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json={"can_join": False, "reason": "이미 마감된 공대입니다."}))
        respx.get(WAITLIST_STATUS_URL).mock(return_value=httpx.Response(200, json={"on_waitlist": False}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "파티장 관리" not in resp.text


def test_admin_can_close_party_via_leader_panel_route(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        close_route = respx.post(CLOSE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json={**PARTY, "status": "closed"}))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/close")

    assert resp.status_code == 303
    assert close_route.called
    import json as _json
    assert _json.loads(close_route.calls[0].request.content)["discord_id"] == "999"


# ── 클리어 되돌리기 ──────────────────────────────────────────

def test_admin_sees_revert_panel_on_disbanded_party(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=DISBANDED_PARTY))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "클리어 되돌리기" in resp.text
    assert "파티장 관리" not in resp.text  # 종료된 파티는 일반 관리 패널 대신 되돌리기만


def test_non_admin_does_not_see_revert_panel_on_disbanded_party(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")  # 원래 파티장이었던 사람 — 이제는 관리자 전용
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=DISBANDED_PARTY))
        respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "클리어 되돌리기" not in resp.text


def test_revert_clear_route_forwards_admin_discord_id(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        revert_route = respx.post(REVERT_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "new_status": "recruiting"})
        )
        resp = client.post("/parties/p1/admin-revert-clear")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert revert_route.called
    import json as _json
    assert _json.loads(revert_route.calls[0].request.content) == {"discord_id": "999"}


def test_revert_clear_route_requires_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.post("/parties/p1/admin-revert-clear")

    assert resp.status_code == 403


# ── /admin/parties 목록 ──────────────────────────────────────

def test_admin_parties_page_requires_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/admin/parties")
    assert resp.status_code == 403


def test_admin_parties_page_shows_open_and_closed_tabs(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        respx.get(ADMIN_PARTIES_URL).mock(
            return_value=httpx.Response(200, json={
                "open": [PARTY],
                "closed": [{**DISBANDED_PARTY, "slots": PARTY["slots"], "is_live": True, "created_at": "2026-05-20T10:00:00"}],
            })
        )
        open_resp = client.get("/admin/parties")
        closed_resp = client.get("/admin/parties?tab=closed")

    assert open_resp.status_code == 200
    assert "아르모체(4막)" in open_resp.text
    assert 'data-filter-target="#admin-open-list"' in open_resp.text
    assert closed_resp.status_code == 200
    assert "리더캐릭" in closed_resp.text  # 종료 탭에도 파티장 캐릭터명이 보임
    assert "되돌리기 가능" in closed_resp.text
    assert 'data-filter-target="#admin-closed-list"' in closed_resp.text


def test_admin_parties_page_hides_search_when_tab_is_empty(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="999")
        respx.get(ADMIN_PARTIES_URL).mock(
            return_value=httpx.Response(200, json={"open": [], "closed": []})
        )
        resp = client.get("/admin/parties")

    assert "js-list-filter" not in resp.text
