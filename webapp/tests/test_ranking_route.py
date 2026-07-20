"""웹 /ranking 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

RANKING_URL = "http://bot-server.internal/api/internal/ranking"

ENTRIES = [
    {"discord_id": "111", "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "combat_power": 4300000, "value": 4300000},
    {"discord_id": "222", "character_name": "바드", "character_class": "바드", "item_level": 1710.0, "combat_power": 4100000, "value": 4100000},
    {"discord_id": "111", "character_name": "워로드부캐", "character_class": "워로드", "item_level": 1700.0, "combat_power": 3900000, "value": 3900000},
]


def test_ranking_requires_login(client):
    resp = client.get("/ranking")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_ranking_renders_combat_power_tab(client):
    with respx.mock:
        log_in(client)
        route = respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "combat_power", "entries": ENTRIES})
        )
        resp = client.get("/ranking")

    assert resp.status_code == 200
    assert route.calls.last.request.url.params["metric"] == "combat_power"
    assert "원정대 랭킹" in resp.text
    assert "발키리" in resp.text
    assert "4,300,000" in resp.text  # 전투력은 천단위 콤마
    assert "🥇" in resp.text  # 1위 메달
    # 캐릭터명이 상세 페이지로 링크 (다른 유저 캐릭터는 discord_id 유지)
    assert "discord_id=222" in resp.text
    # 3개 탭
    assert "/ranking?metric=combat_power" in resp.text
    assert "/ranking?metric=item_level" in resp.text
    assert "/ranking?metric=weekly_clears" in resp.text


def test_ranking_combat_power_defaults_to_dps_role(client):
    """전투력 탭을 role 지정 없이 열면 기본값은 딜러이고, 딜러/서포터 토글이 보여야 한다."""
    with respx.mock:
        log_in(client)
        route = respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "combat_power", "role": "dps", "entries": ENTRIES})
        )
        resp = client.get("/ranking")

    assert route.calls.last.request.url.params["role"] == "dps"
    assert 'class="rank-role-btn is-active">딜러' in resp.text
    assert 'href="/ranking?metric=combat_power&role=support"' in resp.text


def test_ranking_combat_power_support_role_is_selectable(client):
    with respx.mock:
        log_in(client)
        route = respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "combat_power", "role": "support", "entries": ENTRIES[:2]})
        )
        resp = client.get("/ranking", params={"metric": "combat_power", "role": "support"})

    assert route.calls.last.request.url.params["role"] == "support"
    assert 'class="rank-role-btn is-active">서포터' in resp.text


def test_ranking_role_toggle_hidden_outside_combat_power_tab(client):
    """딜러/서포터 토글은 전투력 탭에서만 보여야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "item_level", "entries": ENTRIES})
        )
        resp = client.get("/ranking", params={"metric": "item_level"})

    assert "rank-role-toggle" not in resp.text


def test_ranking_invalid_role_falls_back_to_dps(client):
    with respx.mock:
        log_in(client)
        route = respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "combat_power", "role": "dps", "entries": ENTRIES})
        )
        resp = client.get("/ranking", params={"metric": "combat_power", "role": "healer"})

    assert route.calls.last.request.url.params["role"] == "dps"


def test_ranking_role_param_not_sent_for_non_combat_power_metric(client):
    """웹→봇 요청에서 item_level/weekly_clears 탭일 때는 role을 안 보내야 한다
    (전투력 전용 필터라 다른 지표에 섞이면 안 됨)."""
    with respx.mock:
        log_in(client)
        route = respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "item_level", "entries": ENTRIES})
        )
        client.get("/ranking", params={"metric": "item_level"})

    assert "role" not in route.calls.last.request.url.params


def test_ranking_item_level_tab_formats_two_decimals(client):
    # 아이템레벨 탭에서는 value가 아이템레벨(정렬 기준값)이다
    il_entries = [{**e, "value": e["item_level"]} for e in ENTRIES]
    with respx.mock:
        log_in(client)
        respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "item_level", "entries": il_entries})
        )
        resp = client.get("/ranking", params={"metric": "item_level"})

    assert resp.status_code == 200
    assert "1720.00" in resp.text


def test_ranking_empty_state(client):
    with respx.mock:
        log_in(client)
        respx.get(RANKING_URL).mock(
            return_value=httpx.Response(200, json={"metric": "weekly_clears", "entries": []})
        )
        resp = client.get("/ranking", params={"metric": "weekly_clears"})

    assert resp.status_code == 200
    assert "클리어 기록이 아직 없습니다" in resp.text
