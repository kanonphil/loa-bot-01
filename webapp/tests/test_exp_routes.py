"""원정대·더보기 묶음(원정대·랭킹·캐릭터 전투력 기록·설정 골드섬 스위치·계산기 시세·가이드) 검증.
새 봇 엔드포인트(/loa/*, /characters/{name}/history)는 아직 없을 수 있으므로 404여도 화면이 깨지지 않는지를 같이 본다."""
import re

import httpx
import respx

from webapp.routes.character import build_cp_chart
from webapp.tests.conftest import log_in, toast_of, without_toast
from webapp.tests.test_character_detail_route import ARMORY_URL, DETAIL

B = "http://bot-server.internal/api/internal"
CHARACTERS = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "발키리",
               "cached_at": "2026-11-19 01:00:00"}]
RANKING = [
    {"discord_id": "111", "character_name": "발키리", "character_class": "홀리나이트", "value": 2812.45, "cp_growth_7d": 41.2},
    {"discord_id": "222", "character_name": "리퍼짱", "character_class": "리퍼", "value": 2790.1, "cp_growth_7d": -8.75},
    {"discord_id": "333", "character_name": "바드님", "character_class": "바드", "value": 2540.3, "cp_growth_7d": None},
    {"discord_id": "444", "character_name": "건슬", "character_class": "건슬링어", "value": 2398.0, "cp_growth_7d": 77.0},
]


def _order(html: str) -> list[str]:
    """랭킹 표의 캐릭터 이름 순서."""
    return re.findall(r'class="trunc">([^<]+)</span></a>', html)


# ── 원정대 ────────────────────────────────────────────────────

def _mock_expedition(ranking=None, ranking_status=200):
    respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(f"{B}/accounts/list").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/ranking").mock(return_value=httpx.Response(ranking_status, json={"entries": ranking or []}))


def test_expedition_shows_combat_power_and_growth_from_ranking(client):
    with respx.mock:
        log_in(client)
        _mock_expedition(RANKING)
        resp = client.get("/expedition")
    assert "2,812.45" in resp.text
    assert "▲ +41.20" in resp.text  # 색뿐 아니라 부호·기호로도 구분
    assert "동기화 " in resp.text and "2,790.10" not in resp.text  # 남의 캐릭터는 내 목록에 안 나온다


def test_expedition_survives_ranking_failure(client):
    with respx.mock:
        log_in(client)
        _mock_expedition(ranking_status=500)
        resp = client.get("/expedition")
    assert resp.status_code == 200
    assert "발키리" in resp.text and "전투력" in resp.text


def test_sync_pending_shows_info_toast_not_error(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/characters/sync").mock(return_value=httpx.Response(200, json={"success": True, "pending": True}))
        resp = client.post("/expedition/sync")
    text, kind = toast_of(resp.headers["location"])
    assert kind == "info" and "뒤에서 계속 진행 중" in text


def test_sync_timeout_is_treated_as_pending(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/characters/sync").mock(side_effect=httpx.ReadTimeout("slow"))
        resp = client.post("/expedition/sync", data={"next": "/main"})
    assert resp.status_code == 303 and without_toast(resp.headers["location"]) == "/main"
    assert toast_of(resp.headers["location"])[1] == "info"


def test_add_character_json_mode_returns_reason_for_inline_error(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/characters/add").mock(return_value=httpx.Response(200, json={"success": False, "reason": "찾을 수 없는 캐릭터입니다."}))
        resp = client.post("/expedition/add", data={"character_name": "없음"}, headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False and resp.json()["reason"] == "찾을 수 없는 캐릭터입니다."


def test_add_character_json_mode_success_gives_redirect_with_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/characters/add").mock(
            return_value=httpx.Response(200, json={"success": True, "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}))
        resp = client.post("/expedition/add", data={"character_name": " 발키리 "}, headers={"Accept": "application/json"})
    data = resp.json()
    assert data["success"] is True and without_toast(data["redirect"]) == "/expedition"
    assert "등록 완료" in toast_of(data["redirect"])[0]


def test_add_account_json_mode_failure(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/accounts/add").mock(return_value=httpx.Response(200, json={"success": False, "reason": "API 키가 올바르지 않습니다."}))
        resp = client.post("/expedition/add-account", data={"api_key": "x", "character_name": "a"}, headers={"Accept": "application/json"})
    assert resp.json() == {"success": False, "reason": "API 키가 올바르지 않습니다.", "redirect": resp.json()["redirect"]}


# ── 랭킹 ──────────────────────────────────────────────────────

def _mock_ranking(entries=RANKING):
    respx.get(f"{B}/ranking").mock(return_value=httpx.Response(200, json={"metric": "combat_power", "entries": entries}))


def test_ranking_growth_column_uses_sign_text(client):
    with respx.mock:
        log_in(client)
        _mock_ranking()
        resp = client.get("/ranking")
    assert "7일 성장" in resp.text
    assert "▲ +41.20" in resp.text and "▼ −8.75" in resp.text
    assert 'aria-sort="none"' in resp.text


def test_ranking_sort_by_growth_puts_missing_last(client):
    with respx.mock:
        log_in(client)
        _mock_ranking()
        desc = client.get("/ranking?metric=combat_power&role=dps&sort=growth")
        asc = client.get("/ranking?metric=combat_power&role=dps&sort=growth_asc")
    assert _order(desc.text) == ["건슬", "발키리", "리퍼짱", "바드님"]
    assert _order(asc.text) == ["리퍼짱", "발키리", "건슬", "바드님"]
    assert 'aria-sort="descending"' in desc.text and 'aria-sort="ascending"' in asc.text
    # 정렬해도 순위(#)는 전투력 기준 그대로
    assert re.search(r'exp-c-rank num[^>]*>4</td>\s*<td class="exp-c-name"><div class="exp-namecell">\s*<a[^>]*><span class="trunc">건슬', desc.text)


def test_ranking_sort_param_ignored_outside_combat_power(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/ranking").mock(return_value=httpx.Response(200, json={"metric": "item_level", "entries": RANKING}))
        resp = client.get("/ranking?metric=item_level&sort=growth")
    assert "7일 성장" not in resp.text
    assert _order(resp.text) == ["발키리", "리퍼짱", "바드님", "건슬"]


def test_ranking_entries_without_growth_field_still_render(client):
    with respx.mock:
        log_in(client)
        _mock_ranking([{"discord_id": "1", "character_name": "구형", "character_class": "버서커", "value": 2000.0}])
        resp = client.get("/ranking?sort=growth")
    assert resp.status_code == 200 and "구형" in resp.text


# ── 캐릭터 상세: 전투력 기록 카드 ─────────────────────────────────

def _history(n):
    return {"items": [{"date": f"2026-11-{d:02d}", "combat_power": 2700 + d * 3.5, "item_level": 1735.0} for d in range(1, n + 1)]}


def test_character_detail_shows_history_chart(client):
    with respx.mock:
        log_in(client)
        respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        route = respx.get(f"{B}/characters/%EB%B0%9C%ED%82%A4%EB%A6%AC/history").mock(return_value=httpx.Response(200, json=_history(10)))
        resp = client.get("/characters/발키리")
    assert route.called and route.calls.last.request.url.params["days"] == "90"
    assert "전투력 기록" in resp.text and "<polyline" in resp.text
    assert "▲ +31.50" in resp.text  # 1일 → 10일 사이 9일 × 3.5
    assert 'role="img"' in resp.text


def test_character_detail_history_with_single_point_shows_empty_state(client):
    with respx.mock:
        log_in(client)
        respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        respx.get(f"{B}/characters/%EB%B0%9C%ED%82%A4%EB%A6%AC/history").mock(return_value=httpx.Response(200, json=_history(1)))
        resp = client.get("/characters/발키리")
    assert "<polyline" not in resp.text and "이틀 이상 쌓이면" in resp.text


def test_character_detail_history_404_does_not_break_page(client):
    with respx.mock:
        log_in(client)
        respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        respx.get(f"{B}/characters/%EB%B0%9C%ED%82%A4%EB%A6%AC/history").mock(return_value=httpx.Response(404, json={"detail": "nf"}))
        resp = client.get("/characters/발키리")
    assert resp.status_code == 200 and "발키리" in resp.text and "이틀 이상 쌓이면" in resp.text


def test_build_cp_chart_geometry_and_flat_series():
    chart = build_cp_chart([{"date": "2026-11-01", "combat_power": 100}, {"date": "2026-11-02", "combat_power": 150}, {"date": "2026-11-03", "combat_power": 125}])
    assert chart["delta"] == 25 and chart["low"] == 100 and chart["high"] == 150
    assert chart["end_x"] == 100.0 and 8 <= chart["end_y"] <= 92
    flat = build_cp_chart([{"date": "a", "combat_power": 5}, {"date": "b", "combat_power": 5}])
    assert flat["end_y"] == 50.0 and flat["delta"] == 0
    assert build_cp_chart([{"date": "a", "combat_power": 5}]) is None
    assert build_cp_chart([{"date": "a", "combat_power": "x"}, {"date": "b"}]) is None
    assert build_cp_chart(None) is None


# ── 설정: 골드섬 알림 스위치 ───────────────────────────────────────

def _mock_settings_bot(overview=None, overview_status=200):
    respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{B}/subscriptions").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{B}/preferences").mock(return_value=httpx.Response(200, json={"pre_notify_hours": 1.0, "choices": [0.0, 1.0]}))
    respx.get(f"{B}/loa/overview").mock(return_value=httpx.Response(overview_status, json=overview or {}))


def _gold_switch(html: str) -> tuple[str, bool]:
    m = re.search(r'<button[^>]*aria-checked="(true|false)" aria-labelledby="set-gold"([^>]*)>', html)
    assert m, "골드섬 스위치가 없습니다"
    return m.group(1), "disabled" in m.group(2)


def test_settings_gold_switch_reflects_subscription(client):
    with respx.mock:
        log_in(client)
        _mock_settings_bot({"available": True, "gold_island_subscribed": True})
        resp = client.get("/settings")
    assert _gold_switch(resp.text) == ("true", False)
    assert 'name="enabled" value="0"' in resp.text  # 다음 제출은 끄기


def test_settings_gold_switch_disabled_when_bot_has_no_endpoint(client):
    with respx.mock:
        log_in(client)
        _mock_settings_bot(overview_status=404)
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert _gold_switch(resp.text) == ("false", True)
    assert "불러오지 못함" in resp.text


def test_settings_warns_when_loa_data_unavailable(client):
    with respx.mock:
        log_in(client)
        _mock_settings_bot({"available": False, "reason": "키 없음", "gold_island_subscribed": False})
        resp = client.get("/settings")
    assert "알림이 가지 않을 수 있습니다" in resp.text


def test_gold_island_post_json_and_redirect_modes(client):
    with respx.mock:
        log_in(client)
        route = respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(200, json={"success": True, "enabled": True}))
        as_json = client.post("/settings/gold-island", data={"enabled": "1"}, headers={"Accept": "application/json"})
        plain = client.post("/settings/gold-island", data={"enabled": "1"})
    import json as _json

    assert _json.loads(route.calls[0].request.content) == {"discord_id": "111", "enabled": True}
    assert as_json.json()["success"] is True and "켰습니다" in as_json.json()["message"]
    assert plain.status_code == 303 and without_toast(plain.headers["location"]) == "/settings"
    assert toast_of(plain.headers["location"]) == ("골드섬 알림을 켰습니다.", "success")


def test_gold_island_post_off_and_bot_404(client):
    with respx.mock:
        log_in(client)
        respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(404))
        resp = client.post("/settings/gold-island", data={"enabled": "0"}, headers={"Accept": "application/json"})
        plain = client.post("/settings/gold-island", data={"enabled": "0"})
    assert resp.json()["success"] is False and "지원하지 않습니다" in resp.json()["reason"]
    assert toast_of(plain.headers["location"])[1] == "error"


def test_gold_island_post_requires_login(client):
    resp = client.post("/settings/gold-island", data={"enabled": "1"})
    assert resp.status_code in (302, 303, 307)


# ── 계산기: 시세에서 가져오기 ──────────────────────────────────────

PRICES = {"available": True, "fetched_at": "2026-11-19T20:00:00+09:00", "items": [
    {"id": "1", "name": "유물 각인서 원한", "icon": "", "current": 143000, "yday_avg": 139000.0, "change_pct": 2.9, "history": []},
    {"id": "2", "name": "깨진 항목", "icon": "", "current": 0, "yday_avg": 1.0, "change_pct": 0.0, "history": []},
]}


def test_calculator_shows_price_select_when_items_exist(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/loa/prices").mock(return_value=httpx.Response(200, json=PRICES))
        resp = client.get("/tools/auction-calculator")
    assert 'id="calc-market"' in resp.text
    assert 'value="143000"' in resp.text and "유물 각인서 원한" in resp.text and "(+2.9%)" in resp.text
    assert "깨진 항목" not in resp.text  # 현재가가 없는 항목은 거른다
    assert "board-write-label" not in resp.text


def test_calculator_hides_price_select_when_empty_unavailable_or_404(client):
    for status, body in ((200, {"available": True, "items": []}), (200, {"available": False, "items": [{"name": "x", "current": 1}]}), (404, {})):
        with respx.mock:
            log_in(client)
            respx.get(f"{B}/loa/prices").mock(return_value=httpx.Response(status, json=body))
            resp = client.get("/tools/auction-calculator")
        assert resp.status_code == 200 and 'id="calc-market"' not in resp.text and 'id="calc-price"' in resp.text


# ── 가이드 · 더보기 ───────────────────────────────────────────────

def test_guide_describes_new_menu_and_has_title_when_logged_out(client):
    with respx.mock:
        log_in(client)
        member = client.get("/guide")
    anon = client.__class__(client.app, follow_redirects=False).get("/guide")
    for word in ("홈", "공대", "원정대", "더보기", "알림 종", "숙제표", "공대 열기", "골드섬"):
        assert word in member.text
    assert "/raid-check" not in member.text and "/invites" not in member.text  # 사라진 메뉴로 안내하지 않는다
    assert anon.status_code == 200 and anon.text.count("<h1>이용 가이드</h1>") == 1
    assert member.text.count("<h1>이용 가이드</h1>") == 1  # 머리줄에만


def test_more_groups_rows_with_section_labels(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/more")
    for label in ("설정", "도구", "도움말"):
        assert f">{label}</h2>" in resp.text
    assert "/static/pages/exp.css" in resp.text
