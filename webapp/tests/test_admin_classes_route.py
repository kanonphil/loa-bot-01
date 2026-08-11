"""관리자 직업 관리(/admin/classes) — 레이드 관리에서 분리된 별도 페이지. 봇 서버는 respx로 모킹.

사용자가 "레이드 관리에 왜 직업이 껴있냐", "직업 목록이 늘어날수록 가로로도
길어져서 불편하다"고 지적해 별도 페이지 + 컴팩트 chip 그리드로 재설계했다."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

JOB_CLASSES_URL = "http://bot-server.internal/api/internal/job-classes"
ADD_CLASS_URL = "http://bot-server.internal/api/internal/admin/classes/add"
DELETE_CLASS_URL = "http://bot-server.internal/api/internal/admin/classes/delete"

JOB_CLASSES = [{"name": "워로드", "is_support": 0}, {"name": "홀리나이트", "is_support": 1}]


def test_non_admin_gets_403(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999-someone-else"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/admin/classes")
    assert resp.status_code == 403


def test_admin_sees_class_list_and_search_box(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(JOB_CLASSES_URL).mock(return_value=httpx.Response(200, json=JOB_CLASSES))
        resp = client.get("/admin/classes")

    assert resp.status_code == 200
    assert "워로드" in resp.text
    assert "홀리나이트" in resp.text
    assert "서포터" in resp.text
    assert 'id="class-search"' in resp.text  # 검색창(가로로 늘어지는 문제 대응)


def test_add_class_forwards_discord_id_and_redirects(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.post(ADD_CLASS_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        resp = client.post(
            "/admin/classes/add",
            data={"name": "새직업", "is_support": "on"},
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/classes"
    import json as _json

    body = _json.loads(route.calls[0].request.content)
    assert body == {"discord_id": "111", "name": "새직업", "is_support": True}


def test_delete_class_failure_redirects_with_error(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(DELETE_CLASS_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "관리자 권한이 없습니다."})
        )
        resp = client.post("/admin/classes/delete", data={"name": "워로드"})
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/classes?error=")
