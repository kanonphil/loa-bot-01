"""웹 관리자의 "유저 관리" 기능 검증(/admin/users) — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

USERS_URL = "http://bot-server.internal/api/internal/admin/users"
CHARACTERS_URL = "http://bot-server.internal/api/internal/admin/users/222/characters"
HISTORY_URL = "http://bot-server.internal/api/internal/admin/users/222/history"
DELETE_URL = "http://bot-server.internal/api/internal/admin/users/222/delete"

USERS = [
    {"discord_id": "222", "registered_at": "2026-05-01T00:00:00", "representative": "메인캐릭"},
    {"discord_id": "333", "registered_at": "2026-05-02T00:00:00", "representative": None},
]


def test_non_admin_gets_403(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999-someone-else"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/admin/users")
    assert resp.status_code == 403


def test_admin_sees_user_list(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(USERS_URL).mock(return_value=httpx.Response(200, json=USERS))
        resp = client.get("/admin/users")

    assert resp.status_code == 200
    assert "메인캐릭" in resp.text
    assert "333" in resp.text  # 대표 캐릭터 없는 유저는 discord_id로 표시


def test_admin_sees_empty_state(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(USERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/admin/users")

    assert resp.status_code == 200
    assert "등록된 유저가 없습니다" in resp.text


def test_admin_expands_user_details(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(CHARACTERS_URL).mock(
            return_value=httpx.Response(200, json=[{"character_name": "메인캐릭", "character_class": "워로드", "item_level": 1710.0}])
        )
        respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "entries": [
                        {
                            "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
                            "character_name": "메인캐릭", "role": "dps", "status": "disbanded",
                            "scheduled_time": "05/20 20:00",
                        }
                    ],
                    "has_more": False, "total_count": 1,
                },
            )
        )
        resp = client.get("/admin/users/222/details")

    assert resp.status_code == 200
    assert "메인캐릭" in resp.text
    assert "워로드" in resp.text
    assert "아르모체(4막) 노말" in resp.text
    assert "클리어" in resp.text  # disbanded → status_label


def test_admin_deletes_user(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        delete_route = respx.post(DELETE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/users/222/delete")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/users"
    assert delete_route.called
    import json as _json
    payload = _json.loads(delete_route.calls[0].request.content)
    assert payload == {"discord_id": "111"}


def test_admin_delete_user_shows_error_on_failure(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(DELETE_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "관리자 권한이 없습니다."})
        )
        resp = client.post("/admin/users/222/delete")

    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


# ── 가입일 / API 만료 의심 ──────────────────────────────────────

def test_admin_user_list_shows_registered_date_and_stale_chip(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    users = [
        {"discord_id": "222", "registered_at": "2026-05-01T00:00:00", "representative": "메인캐릭", "last_sync": "2026-05-02 04:00:00"},
        {"discord_id": "333", "registered_at": "2026-05-02T00:00:00", "representative": "최신캐릭", "last_sync": None},
    ]
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(USERS_URL).mock(return_value=httpx.Response(200, json=users))
        resp = client.get("/admin/users")
        stale = client.get("/admin/users?filter=stale")
    assert "가입 2026-05-01" in resp.text
    assert "일 동기화 안 됨" in resp.text
    assert "동기화 기록 없음" in resp.text
    assert "API 만료 의심" in resp.text
    assert "메인캐릭" in stale.text and "최신캐릭" in stale.text


def test_admin_user_stale_filter_hides_fresh_users(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    users = [
        {"discord_id": "222", "registered_at": "2026-05-01T00:00:00", "representative": "방금동기화", "last_sync": fresh},
        {"discord_id": "333", "registered_at": "2026-05-02T00:00:00", "representative": "오래됨", "last_sync": "2026-01-01 00:00:00"},
    ]
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(USERS_URL).mock(return_value=httpx.Response(200, json=users))
        resp = client.get("/admin/users?filter=stale")
    assert "오래됨" in resp.text
    assert "방금동기화" not in resp.text
