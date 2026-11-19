"""홈(/main) — 숙제표·할 일·일정·로아 카드, 옛 주소 이동, 체크 토글 JSON.
봇 서버는 respx로 모킹한다. 로아 API 카드는 봇 엔드포인트가 없어도(404)·느려도·available=false여도 홈이 떠야 한다."""
from datetime import datetime, timedelta, timezone

import httpx
import respx

from webapp.tests.conftest import log_in, toast_of, without_toast

B = "http://bot-server.internal/api/internal"
KST = timezone(timedelta(hours=9))
ME = "111"
NOW = datetime.now(KST)
SOON = (NOW + timedelta(hours=3)).isoformat()
LATER = (NOW + timedelta(days=2)).isoformat()
PAST = (NOW - timedelta(hours=3)).isoformat()


def _raid(name, short, diffs, gold=None):
    return {"raid_name": name, "short_name": short, "icon": "x", "category": "카제로스",
            "difficulties": diffs, "difficulty_gold": gold or {}}


def _char(name, level, completions=(), raids=None, gold=(0, 0), visible=None, done_count=0):
    raids = raids if raids is not None else [_raid("아르모체(4막)", "4막", ["노말", "하드"], {"노말": 1000, "하드": 2000}), _raid("종막", "종막", ["노말"])]
    vis = visible if visible is not None else [r["raid_name"] for r in raids]
    return {"character_name": name, "character_class": "워로드", "item_level": level, "account_label": "a", "is_support": False,
            "completions": list(completions), "selection": {"customized": False, "selected_raids": []},
            "applicable_raids": raids, "visible_raid_names": vis, "done_count": done_count, "total_slots": len(vis),
            "gold_earned": gold[0], "gold_total": gold[1]}


EXTREME_RAID = {"is_extreme": True, "is_active": True, "short_name": "익스", "available_from": None,
                "available_until": (NOW + timedelta(days=5)).isoformat(), "difficulties": {"노말": {"min_level": 1700}, "하드": {"min_level": 1900}}}


def summary(chars=None, extreme=True, gold=None, cleared=None):
    ext = []
    if extreme:
        ext = [{"raid_name": "카멘 익스트림", "short_name": "익스", "available_from": None, "available_until": EXTREME_RAID["available_until"],
                "difficulties": EXTREME_RAID["difficulties"], "cleared": cleared is not None,
                "character_name": cleared[0] if cleared else None, "difficulty": cleared[1] if cleared else None}]
    return {"week_key": "w", "characters": chars if chars is not None else [_char("발키리", 1735.0, ["아르모체(4막)_하드"], done_count=1)],
            "raids": {"카멘 익스트림": EXTREME_RAID} if extreme else {}, "categories": [], "support_classes": [],
            "extreme": ext, **({"gold": gold} if gold else {})}


def mock_home(sm=None, parties=None, invites=None, overview=None, prices=None):
    respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=sm if sm is not None else summary()))
    respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=parties or []))
    respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(200, json=invites or []))
    respx.get(f"{B}/support-classes").mock(return_value=httpx.Response(200, json=["바드"]))
    respx.get(f"{B}/parties/700/eligibility").mock(return_value=httpx.Response(200, json={
        "can_join": True, "qualifying": [{"name": "발키리", "class": "워로드", "level": 1735.0}]}))
    respx.get(f"{B}/loa/overview").mock(return_value=overview or httpx.Response(404))
    respx.get(f"{B}/loa/prices").mock(return_value=prices or httpx.Response(404))


def party(mid, leader, status="recruiting", when=SOON, slots=None, raid="종막"):
    return {"message_id": mid, "raid_name": raid, "difficulty": "노말", "proficiency": "숙련", "leader_id": leader,
            "scheduled_time": "t", "scheduled_datetime": when, "total_slots": 8, "min_level": 1700, "status": status, "memo": None,
            "slots": slots if slots is not None else [{"slot_number": 1, "discord_id": leader, "character_name": "x", "character_class": "워로드", "role": "dps"}]}


INVITE = {"message_id": "700", "slot_number": 3, "invited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
          "raid_name": "카멘", "difficulty": "하드", "proficiency": "숙련", "scheduled_time": "t", "scheduled_datetime": LATER,
          "leader_id": "222", "min_level": 1700, "status": "recruiting"}


def get_home(client, **kw):
    with respx.mock:
        log_in(client)
        mock_home(**kw)
        return client.get("/main")


# ── 숙제표 ──────────────────────────────────────────────

def test_home_requires_login(client):
    resp = client.get("/main")
    assert resp.status_code in (302, 307) and resp.headers["location"] == "/login"


def test_home_renders_homework_table_with_done_state(client):
    resp = get_home(client)
    body = resp.text
    assert resp.status_code == 200
    assert "이번 주" in body and "리셋까지" in body
    assert '<span data-hw-done>1</span>/<span data-hw-total>2</span>' in body
    # 한 번에 숙제표 호출 하나(캐릭터마다 왕복하지 않음)
    assert 'data-char="발키리" data-raid="아르모체(4막)"' in body
    assert 'data-diff="하드" aria-pressed="true" class="on"' in body
    assert "레이드 고르기" in body and "/raid-check/history" in body
    assert 'href="/raid-check/select/%EB%B0%9C%ED%82%A4%EB%A6%AC"' in body  # 캐릭터 1명이면 바로 이동


def test_home_choose_raid_menu_when_multiple_characters(client):
    resp = get_home(client, sm=summary([_char("발키리", 1735.0), _char("부캐", 1700.0)]))
    assert 'aria-controls="hw-select-menu"' in resp.text
    assert resp.text.count('href="/raid-check/select/') == 2


def test_home_filter_on_by_default_above_six_characters(client):
    chars = [_char(f"캐{i}", 1700.0, ["아르모체(4막)_노말", "종막_노말"], done_count=2) for i in range(6)] + [_char("남음", 1700.0), _char("남음2", 1700.0)]
    resp = get_home(client, sm=summary(chars))
    assert 'aria-pressed="true">숙제 남은 캐릭터만' in resp.text
    assert resp.text.count('data-row="캐0"') == 2 and 'data-row="캐0" data-done="2" data-total="2" hidden' in resp.text
    assert 'data-row="남음" data-done="0" data-total="2" hidden' not in resp.text


def test_home_scrolls_inside_card_when_many_raids(client):
    raids = [_raid(f"r{i}", f"r{i}", ["노말"]) for i in range(6)]
    resp = get_home(client, sm=summary([_char("발키리", 1735.0, raids=raids)]))
    assert "hw-scroll hw-desktop is-wide" in resp.text


def test_home_hides_raid_not_visible_for_character(client):
    raids = [_raid("아르모체(4막)", "4막", ["노말"]), _raid("종막", "종막", ["노말"])]
    resp = get_home(client, sm=summary([_char("발키리", 1735.0, raids=raids, visible=["아르모체(4막)"])]))
    assert 'data-raid="종막"' not in resp.text


def test_home_extreme_row_set_and_cleared(client):
    chars = [_char("발키리", 1735.0), _char("부캐", 1700.0)]
    body = get_home(client, sm=summary(chars)).text
    assert "원정대 주 1회" in body
    assert 'data-x-raid="카멘 익스트림"' in body
    # 노말(1700↑)은 둘 다 입장 가능 → 고르는 메뉴, 하드(1900↑)는 아무도 못 감 → 잠금
    assert 'data-x-pick="부캐" data-x-diff="노말"' in body
    assert 'class="locked" data-diff="하드"' in body
    cleared = get_home(client, sm=summary(chars, cleared=("발키리", "노말"))).text
    assert "data-x-clear" in cleared and "<b>발키리</b>로 클리어" in cleared


def test_home_without_characters_shows_next_action(client):
    resp = get_home(client, sm=summary([], extreme=False))
    assert "등록된 캐릭터가 없습니다" in resp.text and "/expedition" in resp.text


def test_home_survives_summary_failure(client):
    with respx.mock:
        log_in(client)
        mock_home()
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(500))
        resp = client.get("/main")
    assert resp.status_code == 200 and "숙제표를 불러오지 못했습니다" in resp.text


# ── 골드 ────────────────────────────────────────────────

def test_home_gold_card_only_when_gold_set(client):
    assert "이번 주 골드" not in get_home(client).text
    chars = [_char("발키리", 1735.0, gold=(1000, 3000))]
    body = get_home(client, sm=summary(chars, gold={"earned": 1000, "total": 3000})).text
    assert "이번 주 골드" in body and "1,000" in body and "3,000" in body


def test_gold_fragment_route(client):
    with respx.mock:
        log_in(client)
        mock_home(sm=summary(gold={"earned": 5, "total": 10}))
        resp = client.get("/main/gold")
    assert resp.status_code == 200 and 'id="home-gold"' in resp.text


# ── 할 일·일정·들어갈 만한 공대 ───────────────────────────

def test_home_todo_has_invite_accept_and_overdue_actions(client):
    overdue = party("p9", ME, status="full", when=PAST)
    resp = get_home(client, invites=[INVITE], parties=[overdue])
    body = resp.text
    assert 'id="todo"' in body and "2건" in body
    assert 'action="/invites/700/accept"' in body and 'id="decline-700"' in body
    assert 'action="/parties/p9/clear"' in body and 'action="/parties/p9/cancel"' in body
    assert "data-confirm-title" in body


def test_home_overdue_only_for_my_parties(client):
    body = get_home(client, parties=[party("p9", "999", status="full", when=PAST)]).text
    assert 'id="todo"' not in body


def test_home_schedule_and_opportunities(client):
    mine = party("p1", ME, when=SOON, raid="아르모체(4막)")
    other = party("p2", "999", when=LATER, raid="종막", slots=[])
    body = get_home(client, parties=[mine, other], invites=[INVITE]).text
    assert "내 일정" in body and "/parties/p1" in body and "초대 대기 중" in body
    assert "들어갈 만한 공대" in body and "/parties/p2" in body


def test_home_invite_without_eligible_character_shows_reason(client):
    with respx.mock:
        log_in(client)
        mock_home(invites=[INVITE])
        respx.get(f"{B}/parties/700/eligibility").mock(return_value=httpx.Response(200, json={"can_join": False, "qualifying": [], "reason": "레벨이 부족합니다."}))
        body = client.get("/main").text
    assert "레벨이 부족합니다." in body and 'id="decline-700"' in body


# ── 로아 API 카드 ─────────────────────────────────────────

OVERVIEW = {
    "available": True, "reason": None, "fetched_at": NOW.isoformat(),
    "maintenance": {"active": True, "title": "정기 점검 안내", "starts_at": NOW.replace(hour=6, minute=0).isoformat(),
                    "ends_at": NOW.replace(hour=10, minute=0).isoformat(), "link": "https://example.com/n"},
    "notices": [], "gold_island_subscribed": True,
    "events": [{"title": "이벤트 A", "link": "https://example.com/e", "end": (NOW + timedelta(days=2)).isoformat()},
               {"title": "끝난 이벤트", "link": "", "end": (NOW - timedelta(days=1)).isoformat()}],
    "today": [{"category": "모험 섬", "name": "섬 A", "icon": "", "times": [(NOW + timedelta(hours=2, minutes=14)).isoformat()],
               "rewards": [{"name": "골드"}], "is_gold": True},
              {"category": "필드보스", "name": "보스 A", "icon": "", "times": [], "rewards": [], "is_gold": False}],
}
PRICES = {"available": True, "items": [{"id": 1, "name": "재료 A", "change_pct": 13.6, "history": [{"date": "d", "avg": 1}, {"date": "e", "avg": 2}]}]}


def test_home_loa_cards_render_when_available(client):
    body = get_home(client, overview=httpx.Response(200, json=OVERVIEW), prices=httpx.Response(200, json=PRICES)).text
    assert "정기 점검 안내" in body and "공지 보기" in body
    assert "오늘의 콘텐츠" in body and "섬 A" in body and "골드" in body and "2시간 " in body
    assert 'data-today-tab="1"' in body and "필드보스" in body
    assert 'aria-checked="true"' in body and "data-gold-switch" in body
    assert "진행 중 이벤트" in body and "이벤트 A" in body and "끝난 이벤트" not in body
    assert "시세" in body and "+13.6%" in body and "/tools/auction-calculator" in body


def test_home_loa_cards_vanish_when_bot_endpoint_missing(client):
    resp = get_home(client)  # 404
    body = resp.text
    assert resp.status_code == 200
    for label in ("오늘의 콘텐츠", "진행 중 이벤트", "시세", "점검"):
        assert label not in body


def test_home_loa_cards_when_unavailable_shows_muted_reason(client):
    ov = httpx.Response(200, json={"available": False, "reason": "로스트아크 API 키가 설정되지 않았습니다."})
    body = get_home(client, overview=ov, prices=httpx.Response(200, json={"available": False})).text
    assert "로스트아크 API 키가 설정되지 않았습니다." in body
    assert "진행 중 이벤트" not in body and 'id="price-title"' not in body


def test_home_survives_loa_timeout(client):
    with respx.mock:
        log_in(client)
        mock_home()
        respx.get(f"{B}/loa/overview").mock(side_effect=httpx.ReadTimeout("slow"))
        respx.get(f"{B}/loa/prices").mock(side_effect=httpx.ConnectError("down"))
        resp = client.get("/main")
    assert resp.status_code == 200 and "숙제" in resp.text


def test_prices_card_hidden_when_no_items(client):
    body = get_home(client, prices=httpx.Response(200, json={"available": True, "items": []})).text
    assert 'id="price-title"' not in body


# ── 골드섬 알림 스위치 ────────────────────────────────────

def test_gold_island_switch_json(client):
    with respx.mock:
        log_in(client)
        route = respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(200, json={"success": True, "enabled": True}))
        resp = client.post("/loa/gold-island-subscription", json={"enabled": True}, headers={"Accept": "application/json"})
    assert resp.json() == {"success": True, "enabled": True, "reason": None}
    assert route.called and b'"enabled":true' in route.calls[0].request.content.replace(b" ", b"")


def test_gold_island_switch_bot_missing_reports_failure(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(404))
        resp = client.post("/loa/gold-island-subscription", json={"enabled": True}, headers={"Accept": "application/json"})
    body = resp.json()
    assert body["success"] is False and body["enabled"] is False and body["reason"]


def test_gold_island_switch_form_redirects_with_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(200, json={"success": True, "enabled": False}))
        resp = client.post("/loa/gold-island-subscription", data={"enabled": "false"})
    assert resp.status_code == 303 and without_toast(resp.headers["location"]) == "/main"
    assert toast_of(resp.headers["location"])[1] == "success"


# ── 옛 주소 ───────────────────────────────────────────────

def test_old_pages_redirect_to_home(client):
    with respx.mock:
        log_in(client)
        raid_check = client.get("/raid-check")
        invites = client.get("/invites")
    assert raid_check.status_code == 303 and raid_check.headers["location"] == "/main"
    assert invites.status_code == 303 and invites.headers["location"] == "/main#todo"


def test_home_has_no_temporary_link_row(client):
    assert "home-links" not in get_home(client).text


# ── 체크 토글 ─────────────────────────────────────────────

RAIDS = {"아르모체(4막)": {"short_name": "4막", "icon": "x", "category": "카제로스", "is_extreme": False, "is_active": True,
                           "available_from": None, "available_until": None,
                           "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2},
                                            "하드": {"min_level": 1720, "total_slots": 8, "party_split": 4, "gates": 2}}}}


def mock_toggle_env(toggle_json, completions=("아르모체(4막)_하드",)):
    respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=[
        {"character_name": "발키리", "character_class": "워로드", "item_level": 1735.0, "account_label": "a"}]))
    respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(f"{B}/raid-categories").mock(return_value=httpx.Response(200, json=[{"name": "카제로스", "sort_order": 0, "is_extreme": 0}]))
    respx.get(f"{B}/completions").mock(return_value=httpx.Response(200, json={"week_key": "w", "completions": list(completions)}))
    respx.get(f"{B}/raid-selection").mock(return_value=httpx.Response(200, json={"customized": False, "selected_raids": []}))
    return respx.post(f"{B}/completions/toggle").mock(return_value=httpx.Response(200, json=toggle_json))


FORM = {"raid_name": "아르모체(4막)", "difficulty": "하드", "character_name": "발키리"}
JSON_HDR = {"Accept": "application/json"}


def test_toggle_json_success_returns_progress(client):
    with respx.mock:
        log_in(client)
        route = mock_toggle_env({"success": True, "completed": True})
        resp = client.post("/raid-check/toggle", data=FORM, headers=JSON_HDR)
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "completed": True, "reason": None, "done": 1, "total": 1,
                           "completions": ["아르모체(4막)_하드"]}
    assert route.called


def test_toggle_json_counts_by_raid_not_difficulty(client):
    with respx.mock:
        log_in(client)
        mock_toggle_env({"completed": True}, completions=["아르모체(4막)_노말", "아르모체(4막)_하드"])
        data = client.post("/raid-check/toggle", data=FORM, headers=JSON_HDR).json()
    assert (data["done"], data["total"]) == (1, 1)  # 레이드 단위


def test_toggle_json_honors_bot_rejection(client):
    with respx.mock:
        log_in(client)
        mock_toggle_env({"success": False, "reason": "체크할 수 없는 난이도입니다.", "completed": False})
        resp = client.post("/raid-check/toggle", data=FORM, headers=JSON_HDR)
    assert resp.json()["success"] is False and resp.json()["reason"] == "체크할 수 없는 난이도입니다."


def test_toggle_json_rejects_foreign_character_without_calling_bot(client):
    with respx.mock:
        log_in(client)
        route = mock_toggle_env({"completed": True})
        resp = client.post("/raid-check/toggle", data={**FORM, "character_name": "남의캐릭터"}, headers=JSON_HDR)
    assert resp.status_code == 403 and resp.json()["success"] is False and not route.called


def test_toggle_json_bot_down_is_json_502(client):
    with respx.mock:
        log_in(client)
        route = mock_toggle_env({})
        route.mock(return_value=httpx.Response(500))
        resp = client.post("/raid-check/toggle", data=FORM, headers=JSON_HDR)
    assert resp.status_code == 502 and resp.json()["success"] is False


def test_toggle_without_json_redirects_home_with_toast(client):
    with respx.mock:
        log_in(client)
        mock_toggle_env({"success": True, "completed": True})
        resp = client.post("/raid-check/toggle", data=FORM)
    assert resp.status_code == 303 and without_toast(resp.headers["location"]) == "/main"
    assert toast_of(resp.headers["location"]) == ("발키리 · 4막 하드 완료 체크", "success")


def test_toggle_without_json_failure_is_error_toast(client):
    with respx.mock:
        log_in(client)
        mock_toggle_env({"success": False, "reason": "안 됩니다."})
        resp = client.post("/raid-check/toggle", data=FORM)
    assert toast_of(resp.headers["location"]) == ("안 됩니다.", "error")


def test_extreme_set_and_clear_json(client):
    with respx.mock:
        log_in(client)
        mock_toggle_env({})
        extreme_raids = {**RAIDS, "카멘익스": {**EXTREME_RAID, "short_name": "익스", "icon": "x", "category": "익스트림"}}
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=extreme_raids))
        set_route = respx.post(f"{B}/completions/extreme/set").mock(return_value=httpx.Response(200, json={"success": True}))
        clear_route = respx.post(f"{B}/completions/extreme/clear").mock(return_value=httpx.Response(200, json={"success": False, "reason": "못 합니다."}))
        ok = client.post("/raid-check/extreme/set", data={"raid_name": "카멘익스", "difficulty": "노말", "character_name": "발키리"}, headers=JSON_HDR)
        bad_diff = client.post("/raid-check/extreme/set", data={"raid_name": "카멘익스", "difficulty": "없는난이도", "character_name": "발키리"}, headers=JSON_HDR)
        cleared = client.post("/raid-check/extreme/clear", data={"raid_name": "카멘익스"}, headers=JSON_HDR)
    assert ok.json() == {"success": True, "reason": None} and set_route.called
    assert bad_diff.status_code == 400 and bad_diff.json()["success"] is False
    assert cleared.json() == {"success": False, "reason": "못 합니다."} and clear_route.called


def test_extreme_clear_redirects_home_without_json(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/completions/extreme/clear").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/raid-check/extreme/clear", data={"raid_name": "카멘익스"})
    assert resp.status_code == 303 and without_toast(resp.headers["location"]) == "/main"


# ── 사이드바 숫자 ─────────────────────────────────────────

def test_nav_badges_home_counts_invites_and_overdue(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[party("a", "999"), party("b", ME, status="full", when=PAST)]))
        respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(200, json=[INVITE]))
        resp = client.get("/nav-badges")
    assert resp.json() == {"parties": 1, "invites": 1, "home": 2}


def test_upcoming_maintenance_notice_shows_info_banner():
    """시각 없는 임시 점검 공지(active=False)도 당일엔 안내 배너로 보여야 한다 — 실제 공지 형식."""
    from webapp.routes.dashboard import build_maintenance

    m = build_maintenance({"maintenance": {"active": False, "title": "11월 19일(목) 로스트아크 임시 점검 안내",
                                           "starts_at": None, "ends_at": None,
                                           "link": "https://lostark.game.onstove.com/News/Notice/Views/13600"}})
    assert m and m["active"] is False and "임시 점검" in m["title"] and m["period"] == ""
    assert build_maintenance({"maintenance": None}) is None
    active = build_maintenance({"maintenance": {"active": True, "title": "점검 중"}})
    assert active["active"] is True


def test_today_tabs_put_adventure_islands_first_and_sort_rows_by_next_start():
    """실제 로아 응답 순서(섬 → 카오스게이트 → 모험 섬)대로 두면 일반 섬이 기본 탭이 되고,
    끝난 섬이 시간 순서 없이 위를 차지했다(2026-11-19 운영에서 발견)."""
    from webapp.routes.dashboard import build_today

    KST = timezone(timedelta(hours=9))
    now = datetime(2026, 11, 19, 20, 0, tzinfo=KST)

    def at(h, m=0):
        return datetime(2026, 11, 19, h, m, tzinfo=KST).isoformat()

    items = [{"category": "섬", "name": f"일반{i}", "times": [at(h)]} for i, h in enumerate([22, 21, 19, 23, 18, 12, 21, 22])]
    items += [{"category": "카오스게이트", "name": "카게", "times": [at(21)]}]
    items += [{"category": "모험 섬", "name": "쿵덕쿵", "times": [at(19), at(21), at(23)]}]
    today = build_today({"today": items}, now)

    assert [t["label"] for t in today["tabs"]] == ["모험섬", "카오스게이트", "섬"]
    assert today["tabs"][0]["rows"][0]["time"] == "21:00"
    isles = today["tabs"][2]
    shown = isles["rows"] + isles["more"]
    assert [r["time"] for r in shown] == ["21:00", "21:00", "22:00", "22:00", "23:00", "12:00", "18:00", "19:00"]
    assert [r["past"] for r in shown][-3:] == [True, True, True]
    assert len(isles["rows"]) == 6 and len(isles["more"]) == 2
