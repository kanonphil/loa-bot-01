"""감사(2026-11-18)에서 확인된 인증·보안 결함의 회귀 테스트."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import respx

from webapp import config, guild_info, main
from webapp.auth import dependencies
from webapp.tests.conftest import VERIFY_URL, extract_state, log_in
from webapp.utils import kst_time, safe_local_path, time_ago


# ── 1. 요청마다 등록·관리자 여부 재확인 ─────────────────────────

def test_deleted_user_loses_access_and_session_is_cleared(client):
    with respx.mock:
        log_in(client)
        assert client.get("/tools/auction-calculator").status_code == 200  # 로그인 상태
        dependencies.clear_registration_cache()
        respx.get(VERIFY_URL).mock(return_value=httpx.Response(200, json={"registered": False}))
        resp = client.get("/tools/auction-calculator")
        assert resp.status_code in (302, 307) and resp.headers["location"] == "/login"
        # 세션이 비워졌으니 봇이 다시 등록으로 돌려놔도 로그인 상태가 아니다
        respx.get(VERIFY_URL).mock(return_value=httpx.Response(200, json={"registered": True}))
        assert client.get("/tools/auction-calculator").headers["location"] == "/login"


def test_registration_check_is_cached_per_user(client):
    with respx.mock:
        log_in(client)
        dependencies.clear_registration_cache()
        route = respx.get(VERIFY_URL).mock(return_value=httpx.Response(200, json={"registered": True}))
        before = route.call_count
        for _ in range(3):
            client.get("/tools/auction-calculator")
        assert route.call_count == before + 1


def test_bot_outage_does_not_log_users_out(client):
    with respx.mock:
        log_in(client)
        dependencies.clear_registration_cache()
        respx.get(VERIFY_URL).mock(side_effect=httpx.ConnectError("down"))
        assert client.get("/tools/auction-calculator").headers.get("location") != "/login"


def test_admin_flag_is_recomputed_each_request(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", set())  # 관리자에서 제외됨
        resp = client.get("/admin/raids")
    assert resp.status_code == 403


def test_html_pages_are_not_stored_but_static_is(client):
    """HTML은 no-store — 로그아웃·권한 해제 뒤 뒤로가기로 예전 관리 화면이 보이면 안 된다."""
    with respx.mock:
        log_in(client)
        page = client.get("/tools/auction-calculator")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store, private"
    forbidden = client.get("/admin/raids")
    assert forbidden.status_code == 403 and "no-store" in forbidden.headers["cache-control"]
    static = client.get("/static/style.css?v=1")
    assert "immutable" in static.headers["cache-control"]


# ── 3. 비내비게이션 요청은 401 (login 리다이렉트로 state를 덮어쓰지 않는다) ──

def test_unauthenticated_htmx_gets_401_with_hx_redirect(client):
    resp = client.post("/notifications/read-all", headers={"HX-Request": "true"})
    assert resp.status_code == 401
    assert resp.headers["HX-Redirect"] == "/login"


def test_unauthenticated_event_stream_gets_401(client):
    resp = client.get("/events/parties", headers={"Accept": "text/event-stream"})
    assert resp.status_code == 401
    assert "location" not in resp.headers


def test_unauthenticated_fetch_gets_401_but_navigation_redirects(client):
    assert client.get("/main", headers={"Sec-Fetch-Mode": "cors"}).status_code == 401
    nav = client.get("/main", headers={"Sec-Fetch-Mode": "navigate"})
    assert nav.status_code in (302, 307) and nav.headers["location"] == "/login"


def test_login_reuses_pending_state(client):
    first = extract_state(client.get("/login").headers["location"])
    second = extract_state(client.get("/login").headers["location"])
    assert first == second


def test_login_makes_new_state_when_pending_one_is_old(client, monkeypatch):
    import webapp.routes.auth_routes as ar

    first = extract_state(client.get("/login").headers["location"])
    monkeypatch.setattr(ar, "_STATE_REUSE_SECONDS", -1)
    second = extract_state(client.get("/login").headers["location"])
    assert first != second


# ── 16. /callback 취소·재사용 코드 ──────────────────────────────

def test_callback_without_code_goes_to_login_with_cancel_message(client):
    resp = client.get("/callback", params={"error": "access_denied", "state": "x"})
    assert resp.status_code in (302, 307) and "error=cancelled" in resp.headers["location"]
    page = client.get(resp.headers["location"])
    assert page.status_code == 200 and "취소" in page.text


def test_callback_discord_rejection_is_not_reported_as_bot_failure(client):
    state = extract_state(client.get("/login").headers["location"])
    with respx.mock:
        respx.post("https://discord.com/api/v10/oauth2/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        resp = client.get("/callback", params={"code": "used", "state": state})
    assert resp.status_code in (302, 307) and "error=discord_failed" in resp.headers["location"]


# ── 21. 안전한 이동 경로 ───────────────────────────────────────

def test_safe_local_path_rejects_backslash_and_absolute_urls():
    assert safe_local_path("/main?x=1", "/d") == "/main?x=1"
    for bad in ("/\\evil.com", "//evil.com", "https://evil.com", "evil.com", "/\tfoo", "", None, "/a\\b"):
        assert safe_local_path(bad, "/d") == "/d"


def test_expedition_sync_next_backslash_is_rejected(client):
    with respx.mock:
        log_in(client)
        respx.post("http://bot-server.internal/api/internal/characters/sync").mock(
            return_value=httpx.Response(200, json={"success": True, "updated": 1, "total": 1})
        )
        resp = client.post("/expedition/sync", data={"next": "/\\evil.com"})
    assert resp.headers["location"].startswith("/expedition")


def test_admin_toggle_mode_ignores_protocol_relative_referer(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.post("/admin/toggle-mode", headers={"Referer": "http://testserver///evil.com/x"})
    assert resp.status_code == 303
    assert not resp.headers["location"].startswith("//")


# ── 22. CSRF(Origin/Referer) + POST /logout ────────────────────

def test_post_with_foreign_origin_is_rejected(client):
    with respx.mock:
        log_in(client)
        resp = client.post("/logout", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_post_without_origin_or_referer_is_rejected(client):
    with respx.mock:
        log_in(client)
        client.headers.pop("Origin")
        resp = client.post("/logout")
    assert resp.status_code == 403


def test_post_with_same_host_referer_only_is_allowed(client):
    with respx.mock:
        log_in(client)
        client.headers.pop("Origin")
        resp = client.post("/logout", headers={"Referer": "http://testserver/main"})
    assert resp.status_code == 303


def test_post_from_discord_redirect_host_is_allowed(client):
    resp = client.post("/logout", headers={"Origin": "http://localhost:8001"})
    assert resp.status_code == 303


def test_get_requests_are_not_origin_checked(client):
    assert client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 200


def test_logout_post_and_get_both_clear_session(client):
    with respx.mock:
        log_in(client)
        assert client.post("/logout").status_code == 303
        assert client.get("/expedition").headers["location"] == "/login"
        log_in(client)
        assert client.get("/logout").status_code in (302, 303, 307)
        assert client.get("/expedition").headers["location"] == "/login"


# ── 13. 경로 식별자 검증 ───────────────────────────────────────

def test_path_traversal_message_id_is_rejected_before_calling_bot(client):
    with respx.mock:
        log_in(client)
        leave = respx.post("http://bot-server.internal/api/internal/leave").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        resp = client.post("/parties/%2E%2E/leave", data={})
        assert resp.status_code == 404
        assert not leave.called


def test_bot_client_escapes_path_segments():
    from webapp.clients import bot_client

    assert bot_client._q("../x/y") == "..%2Fx%2Fy"


# ── 15. 캘린더 연도 범위 ───────────────────────────────────────

def test_calendar_extreme_year_does_not_500(client):
    with respx.mock:
        log_in(client)
        respx.get("http://bot-server.internal/api/internal/parties/calendar").mock(
            return_value=httpx.Response(200, json=[])
        )
        for url in ("/calendar?year=9999&month=12", "/calendar?year=0&month=1", "/calendar?view=week&week_start=0001-01-01"):
            assert client.get(url).status_code == 200


# ── 23. party_split 입력 ───────────────────────────────────────

def test_admin_difficulty_non_numeric_split_gives_toast_not_500(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        for path in ("/admin/raids/difficulties/add", "/admin/raids/difficulties/update"):
            resp = client.post(path, data={
                "raid_name": "카멘", "difficulty": "노말", "min_level": "1610", "total_slots": "8",
                "party_split": "abc", "gates": "1",
            })
            assert resp.status_code == 303
            assert "toast_type=error" in resp.headers["location"]


# ── 정적 파일 캐시 ─────────────────────────────────────────────

def test_static_cache_control_depends_on_version_param(client):
    versioned = client.get("/static/style.css?v=123")
    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/static/style.css").headers["cache-control"] == "no-cache"


# ── 20. 길드 아이콘 지연 재시도 ─────────────────────────────────

def test_guild_icon_retries_after_failure_with_backoff(monkeypatch):
    calls = {"n": 0}

    async def fake(guild_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("down")
        return {"icon_url": "https://cdn.example/icon.png"}

    from webapp.clients import bot_client
    monkeypatch.setattr(bot_client, "get_guild_info", fake)
    monkeypatch.setattr(guild_info, "_icon_url", None)
    monkeypatch.setattr(guild_info, "_next_attempt_at", 0.0)
    monkeypatch.setattr(guild_info, "_retry_delay", guild_info._RETRY_MIN_SECONDS)

    async def scenario():
        await guild_info.refresh()                    # 기동 시 실패
        assert guild_info.get_icon_url() is None      # 백오프 중에는 재시도하지 않는다
        assert calls["n"] == 1
        monkeypatch.setattr(guild_info, "_next_attempt_at", 0.0)
        assert guild_info.get_icon_url() is None      # 이번 렌더는 기다리지 않고 백그라운드 시도
        await asyncio.sleep(0.05)
        return guild_info.get_icon_url()

    assert asyncio.run(scenario()) == "https://cdn.example/icon.png"
    assert calls["n"] == 2
    monkeypatch.setattr(guild_info, "_icon_url", None)


# ── 25. 주간 정리 대기 시간 ─────────────────────────────────────

def test_cleanup_sleep_wakes_at_next_weekly_reset():
    kst = timezone(timedelta(hours=9))
    # 수요일 03:00 KST → 같은 날 06:00 리셋까지 3시간 남음(6시간 주기보다 짧다)
    now = datetime(2026, 11, 18, 3, 0, tzinfo=kst)
    assert 3 * 3600 <= main._cleanup_sleep_seconds(now) <= 3 * 3600 + 10
    # 목요일 — 다음 리셋이 멀면 6시간 주기
    assert main._cleanup_sleep_seconds(datetime(2026, 11, 19, 12, 0, tzinfo=kst)) == main.CLEANUP_INTERVAL_SECONDS


# ── 6. 시각 필터 ───────────────────────────────────────────────

def test_kst_time_converts_sqlite_utc_timestamp():
    assert kst_time("2026-11-18 05:00:00") == "2026-11-18 14:00"
    assert kst_time("2026-11-18T05:00:00+00:00", "%m/%d %H:%M") == "11/18 14:00"
    assert kst_time(None) == "" and kst_time("garbage") == ""


def test_time_ago_handles_sqlite_format():
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=13)).strftime("%Y-%m-%d %H:%M:%S")
    assert time_ago(stamp) == "13분 전"


def test_jinja_filters_registered_globally():
    from webapp.templating import templates

    assert templates.env.from_string("{{ v|kst_time }}").render(v="2026-11-18 05:00:00") == "2026-11-18 14:00"
    assert templates.env.from_string("{{ v|time_ago }}").render(v=None) == ""


def test_comment_time_renders_kst_with_relative_label():
    from webapp.templating import templates

    stamp = (datetime.now(timezone.utc) - timedelta(minutes=13)).strftime("%Y-%m-%d %H:%M:%S")
    html = templates.env.get_template("_party_comments_list.html").render(
        comments=[{"id": 1, "author_name": "a", "content": "hi", "created_at": stamp, "source": "discord", "discord_id": "1"}],
        user={"discord_id": "2"}, party={"message_id": "p1"},
    )
    assert "13분 전" in html
    assert f'title="{kst_time(stamp)}"' in html
