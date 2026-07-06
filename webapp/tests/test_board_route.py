"""커뮤니티 게시판 페이지 검증 — 봇 서버는 respx로 모킹."""
import json

import httpx
import respx

from webapp.tests.conftest import log_in

POSTS_URL = "http://bot-server.internal/api/internal/board/posts"
POST1_URL = "http://bot-server.internal/api/internal/board/posts/1"
POST1_COMMENT_URL = "http://bot-server.internal/api/internal/board/posts/1/comments"
POST1_JOIN_URL = "http://bot-server.internal/api/internal/board/posts/1/join"
POST1_LEAVE_URL = "http://bot-server.internal/api/internal/board/posts/1/leave"

POST_LIST = [
    {"id": 1, "guild_id": "test-guild-id", "author_discord_id": "111", "title": "길드 회식",
     "category": "이벤트", "content": "이번주말 회식", "scheduled_datetime": "2026-08-01T20:00:00+09:00",
     "created_at": "2026-07-01 10:00:00", "announced": 1, "reminder_10min_sent": 0, "reminder_start_sent": 0},
    {"id": 2, "guild_id": "test-guild-id", "author_discord_id": "222", "title": "공지사항",
     "category": "공지", "content": "점검 예정", "scheduled_datetime": None,
     "created_at": "2026-07-01 09:00:00", "announced": 0, "reminder_10min_sent": 0, "reminder_start_sent": 0},
]

POST1_DETAIL = {
    **POST_LIST[0],
    "author_name": "길드장",
    "comments": [
        {"id": 1, "post_id": 1, "discord_id": "222", "content": "기대됩니다",
         "created_at": "2026-07-01 11:00:00", "display_name": "댓글러"},
    ],
    "participants": [
        {"post_id": 1, "discord_id": "222", "joined_at": "2026-07-01 11:00:00", "display_name": "댓글러"},
    ],
}


def test_board_list_renders_posts(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(POSTS_URL).mock(return_value=httpx.Response(200, json=POST_LIST))
        resp = client.get("/board")

    assert resp.status_code == 200
    assert "길드 회식" in resp.text
    assert "공지사항" in resp.text


def test_board_list_filters_by_category(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(POSTS_URL, params={"guild_id": "test-guild-id", "category": "이벤트"}).mock(
            return_value=httpx.Response(200, json=[POST_LIST[0]])
        )
        resp = client.get("/board", params={"category": "이벤트"})

    assert resp.status_code == 200
    assert route.called
    assert "길드 회식" in resp.text
    assert "공지사항" not in resp.text


def test_board_create_form_renders(client):
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/board/create")

    assert resp.status_code == 200
    assert "이벤트" in resp.text
    assert "공지" in resp.text
    assert "자유" in resp.text


def test_create_event_post_requires_no_special_handling_for_notice_without_schedule(client):
    """공지/자유 카테고리는 일정 없이도 생성 가능해야 한다 — scheduled_datetime을 빈 문자열로
    보내면 웹 라우트가 None으로 변환해서 넘겨야 한다."""
    with respx.mock:
        log_in(client, discord_id="111")
        create_route = respx.post(POSTS_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "post_id": 5})
        )
        resp = client.post(
            "/board/create",
            data={"title": "새 공지", "category": "공지", "content": "내용", "scheduled_datetime": ""},
        )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/board/5"
    sent_body = create_route.calls.last.request.content
    import json as _json
    payload = _json.loads(sent_body)
    assert payload["scheduled_datetime"] is None
    assert payload["category"] == "공지"


def test_create_post_shows_error_on_failure(client):
    """폼 자체(HTML required)는 통과했지만 봇 서버가 거부하는 경우 — 예: 알 수 없는 카테고리.
    이때 봇이 돌려준 reason이 그대로 에러 메시지로 렌더링돼야 한다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(POSTS_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "존재하지 않는 카테고리입니다."})
        )
        resp = client.post(
            "/board/create",
            data={"title": "제목", "category": "없는카테고리", "content": "내용", "scheduled_datetime": ""},
        )

    assert resp.status_code == 200
    assert "존재하지 않는 카테고리입니다." in resp.text


def test_board_detail_shows_comments_and_participants(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "기대됩니다" in resp.text
    assert "길드 회식" in resp.text


def test_board_detail_shows_resolved_display_names_not_raw_discord_id(client):
    """디스코드 <@id> 멘션은 웹 브라우저에서 안 풀리므로, 봇 서버가 내려준 서버 별명이 그대로 보여야 한다."""
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "길드장" in resp.text
    assert "댓글러" in resp.text
    assert "<@111>" not in resp.text
    assert "<@222>" not in resp.text


def test_board_detail_missing_post_shows_not_found(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, text="null"))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "게시글을 찾을 수 없습니다" in resp.text


def test_author_sees_edit_delete_controls(client):
    with respx.mock:
        log_in(client, discord_id="111")  # author
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "✏️ 수정" in resp.text
    assert "🗑️ 삭제" in resp.text
    # 수정 폼은 "수정" 버튼을 누르기 전엔 숨겨져 있어야 한다
    assert '<form method="post" action="/board/1/edit" class="leader-panel leader-form board-edit-form" id="board-edit-form" hidden>' in resp.text


def test_non_author_does_not_see_edit_delete_controls(client):
    with respx.mock:
        log_in(client, discord_id="222")  # not author
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "✏️ 수정" not in resp.text
    assert "🗑️ 삭제" not in resp.text


def test_join_button_shown_when_not_participant(client):
    with respx.mock:
        log_in(client, discord_id="999")  # not in participants
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "참여하기" in resp.text


def test_leave_button_shown_when_already_participant(client):
    with respx.mock:
        log_in(client, discord_id="222")  # already a participant
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert "나가기" in resp.text


def test_join_calls_bot_endpoint(client):
    with respx.mock:
        log_in(client, discord_id="999")
        join_route = respx.post(POST1_JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post("/board/1/join")

    assert resp.status_code == 200
    assert join_route.called


def test_leave_calls_bot_endpoint(client):
    with respx.mock:
        log_in(client, discord_id="222")
        leave_route = respx.post(POST1_LEAVE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post("/board/1/leave")

    assert resp.status_code == 200
    assert leave_route.called


def test_add_comment_calls_bot_endpoint(client):
    with respx.mock:
        log_in(client, discord_id="222")
        comment_route = respx.post(POST1_COMMENT_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "comment_id": 2})
        )
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post("/board/1/comment", data={"content": "저도 참여합니다"})

    assert resp.status_code == 200
    assert comment_route.called


def test_edit_by_author_calls_patch(client):
    with respx.mock:
        log_in(client, discord_id="111")
        edit_route = respx.patch(POST1_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post(
            "/board/1/edit",
            data={"title": "수정된 제목", "content": "수정된 내용", "scheduled_datetime": ""},
        )

    assert resp.status_code == 200
    assert edit_route.called


def test_edit_rejected_for_non_author_shows_error(client):
    """서버(봇)가 작성자 검증을 하므로, 여기서는 그 reason이 그대로 렌더링되는지 확인한다."""
    with respx.mock:
        log_in(client, discord_id="222")  # not author
        respx.patch(POST1_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "작성자만 수정할 수 있습니다."})
        )
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post(
            "/board/1/edit",
            data={"title": "해킹", "content": "해킹", "scheduled_datetime": ""},
        )

    assert resp.status_code == 200
    assert "작성자만 수정할 수 있습니다." in resp.text


def test_delete_by_author_redirects_to_list(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.delete(POST1_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/board/1/delete")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/board"


def test_delete_rejected_for_non_author_shows_error(client):
    with respx.mock:
        log_in(client, discord_id="222")  # not author
        respx.delete(POST1_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "작성자만 삭제할 수 있습니다."})
        )
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post("/board/1/delete")

    assert resp.status_code == 200
    assert "작성자만 삭제할 수 있습니다." in resp.text


# ── 리치 텍스트 에디터: 저장 전 HTML 정제 ──────────────────────

def test_create_post_sanitizes_script_tags(client):
    """에디터가 만들어낸 HTML은 저장 전에 정제된다 — script/onerror 등 위험 요소는 제거."""
    with respx.mock:
        log_in(client, discord_id="111")
        create_route = respx.post(POSTS_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "post_id": 9})
        )
        resp = client.post(
            "/board/create",
            data={
                "title": "제목",
                "category": "자유",
                "content": '<p>안녕</p><script>alert(1)</script><img src="x" onerror="alert(2)">',
                "scheduled_datetime": "",
            },
        )

    assert resp.status_code == 303
    sent_payload = json.loads(create_route.calls.last.request.content)
    assert "<script>" not in sent_payload["content"]
    assert "onerror" not in sent_payload["content"]
    assert "<p>안녕</p>" in sent_payload["content"]


def test_edit_post_sanitizes_javascript_href(client):
    with respx.mock:
        log_in(client, discord_id="111")
        edit_route = respx.patch(POST1_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=POST1_DETAIL))
        resp = client.post(
            "/board/1/edit",
            data={
                "title": "수정된 제목",
                "content": '<a href="javascript:alert(1)">click me</a>',
                "scheduled_datetime": "",
            },
        )

    assert resp.status_code == 200
    sent_payload = json.loads(edit_route.calls.last.request.content)
    assert "javascript:" not in sent_payload["content"]


def test_board_detail_renders_content_as_html(client):
    """정제된 HTML은 그대로(escape 없이) 렌더되어야 한다 — <p> 태그가 실제 문단으로 표시."""
    post = {**POST1_DETAIL, "content": "<p>사진 추가된 공지</p><img src=\"/static/uploads/board/x.png\" alt=\"img\">"}
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(POST1_URL).mock(return_value=httpx.Response(200, json=post))
        resp = client.get("/board/1")

    assert resp.status_code == 200
    assert '<p>사진 추가된 공지</p>' in resp.text
    assert '<img src="/static/uploads/board/x.png" alt="img">' in resp.text


# ── 이미지 업로드 엔드포인트 ────────────────────────────────

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_upload_image_requires_login(client):
    resp = client.post("/board/upload-image", files={"file": ("a.png", PNG_HEADER, "image/png")})
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_upload_image_accepts_valid_png(client, tmp_path, monkeypatch):
    import webapp.routes.board as board_module

    monkeypatch.setattr(board_module, "UPLOAD_DIR", tmp_path / "board_uploads")

    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.post("/board/upload-image", files={"file": ("a.png", PNG_HEADER, "image/png")})

    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("/static/uploads/board/")
    assert body["url"].endswith(".png")
    saved = list((tmp_path / "board_uploads").iterdir())
    assert len(saved) == 1


def test_upload_image_rejects_non_image_file(client, tmp_path, monkeypatch):
    import webapp.routes.board as board_module

    monkeypatch.setattr(board_module, "UPLOAD_DIR", tmp_path / "board_uploads")

    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.post(
            "/board/upload-image", files={"file": ("evil.png", b"not an image", "image/png")}
        )

    assert resp.status_code == 400


def test_upload_image_rejects_oversized_file(client, tmp_path, monkeypatch):
    import webapp.routes.board as board_module

    monkeypatch.setattr(board_module, "UPLOAD_DIR", tmp_path / "board_uploads")
    oversized = PNG_HEADER + b"\x00" * (5 * 1024 * 1024)

    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.post("/board/upload-image", files={"file": ("big.png", oversized, "image/png")})

    assert resp.status_code == 400
