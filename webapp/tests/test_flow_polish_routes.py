"""플로우 정비 묶음 — 메인 카드(초대·처리 필요 공대·파티장 칩), 모바일 알림 탭/시트, 게스트 셸,
에러 페이지(403/404/422), 캐릭터 상세 뒤로가기, 취소/강퇴 알림 열기."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import respx

from webapp import config, notification_store
from webapp.tests.conftest import log_in, toast_of, without_toast

B = "http://bot-server.internal/api/internal"
KST = timezone(timedelta(hours=9))
ME = "111"
SOON = (datetime.now(KST) + timedelta(hours=3)).isoformat()
PAST = (datetime.now(KST) - timedelta(hours=3)).isoformat()

CHARACTERS = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}]
PROGRESS = {"week_key": "w", "done": 0, "total": 1, "characters": []}
MY_LEADER_PARTY = {
    "message_id": "p1", "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "leader_id": ME, "scheduled_time": "곧", "scheduled_datetime": SOON,
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": ME, "character_name": "발키리", "character_class": "홀리나이트", "role": "dps"}],
}
OVERDUE = {**MY_LEADER_PARTY, "message_id": "p9", "raid_name": "종막", "scheduled_datetime": PAST, "status": "full"}
INVITE = {
    "message_id": "700", "slot_number": 3, "invited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    "raid_name": "카멘", "difficulty": "하드", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": SOON, "leader_id": "222", "min_level": 1700, "status": "recruiting",
}


def _mock_main(parties=None, invites=None):
    respx.get(f"{B}/user-characters").mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=parties or []))
    respx.get(f"{B}/raid-progress").mock(return_value=httpx.Response(200, json=PROGRESS))
    respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(200, json=invites or []))
    respx.get(f"{B}/parties/700/eligibility").mock(return_value=httpx.Response(200, json={
        "can_join": True, "qualifying": [{"name": "발키리", "class": "홀리나이트", "level": 1720.0}],
    }))
    respx.get(f"{B}/support-classes").mock(return_value=httpx.Response(200, json=["홀리나이트"]))


# ── 메인 카드 ───────────────────────────────────────────────

def test_main_shows_invite_card_with_accept_and_decline(client):
    with respx.mock:
        log_in(client)
        _mock_main(invites=[INVITE])
        resp = client.get("/main")
    body = resp.text
    assert "내게 온 초대" in body and "카멘 하드" in body
    assert 'action="/invites/700/accept"' in body and 'id="decline-700"' in body
    assert "만료까지" in body


def test_main_hides_invite_section_when_none(client):
    with respx.mock:
        log_in(client)
        _mock_main()
        resp = client.get("/main")
    assert 'id="decline-' not in resp.text  # 사이드바 메뉴명("내게 온 초대")과 구분해 카드 마커로 확인


def test_main_invite_card_degrades_when_bot_call_fails(client):
    with respx.mock:
        log_in(client)
        _mock_main()
        respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(500, text="boom"))
        resp = client.get("/main")
    assert resp.status_code == 200  # 카드 하나 실패로 메인이 502가 되지 않는다


def test_main_shows_leader_chips_and_overdue_section(client):
    with respx.mock:
        log_in(client)
        _mock_main(parties=[MY_LEADER_PARTY, OVERDUE])
        resp = client.get("/main")
    body = resp.text
    assert "빈자리 7" in body and "서포터 없음" in body
    assert "처리가 필요한 내 공대" in body and "종막 노말" in body
    assert 'action="/parties/p9/clear"' in body and 'action="/parties/p9/cancel"' in body


def test_main_overdue_only_for_my_leader_parties(client):
    with respx.mock:
        log_in(client)
        _mock_main(parties=[{**OVERDUE, "leader_id": "999"}])
        resp = client.get("/main")
    assert "처리가 필요한 내 공대" not in resp.text


# ── 모바일 알림 탭 / 셸 ───────────────────────────────────

def test_bottom_tabs_have_five_entries_with_notification_button(client):
    with respx.mock:
        log_in(client)
        _mock_main()
        resp = client.get("/main")
    tabs = resp.text.split('class="bottom-tabs"')[1].split("</nav>")[0]
    assert 'id="notif-bell-mobile"' in tabs and 'data-notif-badge' in tabs
    assert 'href="/ranking"' not in tabs and 'href="/calendar"' not in tabs
    assert tabs.count("<a ") == 4
    # 패널은 사이드바 밖에서 시트/드롭다운으로 공유
    assert 'id="notif-panel" role="dialog"' in resp.text and 'id="notif-overlay"' in resp.text
    assert 'aria-live="polite"' in resp.text


def test_guest_guide_has_no_authenticated_nav(client):
    resp = client.get("/guide")
    body = resp.text
    assert resp.status_code == 200
    assert 'href="/logout"' not in body and 'href="/expedition"' not in body.split('<main')[0]
    assert 'id="notif-bell"' not in body and "nav-badges.js" not in body and "notifications.js" not in body
    assert 'href="/login"' in body


# ── 에러 페이지 ─────────────────────────────────────────────

def test_forbidden_character_action_renders_error_page(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=CHARACTERS))
        resp = client.post("/raid-check/toggle", data={"raid_name": "x", "difficulty": "y", "character_name": "남의캐릭", "card_index": "0"})
    assert resp.status_code == 403
    assert "본인 캐릭터만 체크할 수 있습니다" in resp.text and "<html" in resp.text


def test_non_admin_gets_error_page_not_json(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id=ME)
        resp = client.get("/admin/raids")
    assert resp.status_code == 403
    assert "관리자만 접근할 수 있습니다" in resp.text and "다시 시도" in resp.text


def test_unknown_page_and_bad_form_render_error_page(client):
    with respx.mock:
        log_in(client)
        missing = client.get("/no-such-page")
        bad_form = client.post("/expedition/add", data={})  # character_name 누락 → 422
    assert missing.status_code == 404 and "페이지를 찾을 수 없습니다" in missing.text
    assert bad_form.status_code == 422 and "입력값이 올바르지 않습니다" in bad_form.text


def test_login_required_still_redirects(client):
    resp = client.get("/parties")
    assert resp.status_code in (302, 307) and resp.headers["location"] == "/login"


def test_htmx_error_is_plain_text(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/no-such-page", headers={"HX-Request": "true"})
    assert resp.status_code == 404 and "<html" not in resp.text


# ── 캐릭터 상세 뒤로가기 ─────────────────────────────────────

def test_character_back_link_follows_origin(client):
    detail = {"character_name": "발키리", "character_class": "홀리나이트", "error": "정보 없음"}
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/armory-detail").mock(return_value=httpx.Response(200, json=detail))
        own = client.get("/characters/발키리")
        from_rank = client.get("/characters/발키리?discord_id=222&back=ranking")
        from_party = client.get("/characters/발키리?discord_id=222&back=party:p1")
    assert 'href="/expedition" class="party-back-link"' in own.text
    assert 'href="/ranking" class="party-back-link"' in from_rank.text and "원정대 랭킹으로" in from_rank.text
    assert 'href="/parties/p1" class="party-back-link"' in from_party.text


# ── 취소/강퇴 알림은 목록으로 ─────────────────────────────────

def test_open_cancelled_notification_goes_to_party_list(client):
    with respx.mock:
        log_in(client, discord_id=ME)
    saved = asyncio.run(notification_store.add_notification("cancelled", "gone", "카멘 공대가 취소되었습니다.", target_discord_id=ME))
    resp = client.get(f"/notifications/{saved['id']}/open")
    assert resp.status_code == 303
    assert without_toast(resp.headers["location"]) == "/parties"
    assert toast_of(resp.headers["location"])[1] == "info"
