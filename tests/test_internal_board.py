"""bot/api/routes/internal.py의 길드 커뮤니티 게시판 엔드포인트 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_channel = MagicMock()
    fake_channel.send = AsyncMock()

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel
    bot_ref.set_bot(None)


def _create_payload(**overrides):
    payload = {
        "discord_id": "111",
        "guild_id": "1",
        "title": "길드 회식",
        "category": "자유",
        "content": "이번 주말에 다같이 모입니다",
        "scheduled_datetime": None,
    }
    payload.update(overrides)
    return payload


# ── 목록/생성 ──────────────────────────────────────────────

def test_list_posts_empty(client, fake_bot):
    resp = client.get("/api/internal/board/posts", params={"guild_id": "1"}, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_post_free_category_without_schedule(client, fake_bot):
    resp = client.post("/api/internal/board/posts", json=_create_payload(), headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["post_id"], int)

    posts = asyncio.run(db.list_board_posts("1"))
    assert len(posts) == 1
    assert posts[0]["category"] == "자유"


def test_create_post_rejects_unknown_category(client, fake_bot):
    resp = client.post(
        "/api/internal/board/posts", json=_create_payload(category="없는카테고리"), headers=HEADERS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


def test_create_post_rejects_empty_title(client, fake_bot):
    resp = client.post("/api/internal/board/posts", json=_create_payload(title="  "), headers=HEADERS)
    assert resp.json()["success"] is False


def test_create_event_post_announces_when_channel_configured(client, fake_bot):
    _, fake_channel = fake_bot
    asyncio.run(db.set_board_channel("1", "555", "777"))

    resp = client.post(
        "/api/internal/board/posts",
        json=_create_payload(category="이벤트", scheduled_datetime="2026-08-01T20:00:00+09:00"),
        headers=HEADERS,
    )
    assert resp.status_code == 200
    post_id = resp.json()["post_id"]

    fake_channel.send.assert_awaited_once()
    sent_text = fake_channel.send.call_args[0][0]
    assert "길드 회식" in sent_text
    assert "<@&777>" in sent_text

    post = asyncio.run(db.get_board_post(post_id))
    assert post["announced"] == 1


def test_announcement_summary_strips_html_tags(client, fake_bot):
    """웹앱 에디터가 저장한 본문은 HTML(<p>, <img> 등)이라 디스코드 알림 요약은
    태그를 제거한 평문이어야 한다 — 안 그러면 알림에 태그가 그대로 노출된다."""
    _, fake_channel = fake_bot
    asyncio.run(db.set_board_channel("1", "555", None))

    resp = client.post(
        "/api/internal/board/posts",
        json=_create_payload(
            category="이벤트",
            content='<p>이번 주말에 다같이 모입니다</p><img src="/static/uploads/board/x.png" alt="poster">',
            scheduled_datetime="2026-08-01T20:00:00+09:00",
        ),
        headers=HEADERS,
    )
    assert resp.status_code == 200

    fake_channel.send.assert_awaited_once()
    sent_text = fake_channel.send.call_args[0][0]
    assert "<p>" not in sent_text
    assert "<img" not in sent_text
    assert "이번 주말에 다같이 모입니다" in sent_text


def test_create_event_post_skips_announcement_when_channel_not_configured(client, fake_bot):
    """채널 미설정이어도 요청 자체는 실패하면 안 되고, announced는 재시도 방지를 위해 1로 마킹된다."""
    resp = client.post(
        "/api/internal/board/posts",
        json=_create_payload(category="이벤트", scheduled_datetime="2026-08-01T20:00:00+09:00"),
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    post = asyncio.run(db.get_board_post(body["post_id"]))
    assert post["announced"] == 1


def test_create_notice_post_does_not_announce(client, fake_bot):
    _, fake_channel = fake_bot
    asyncio.run(db.set_board_channel("1", "555", "777"))

    resp = client.post(
        "/api/internal/board/posts", json=_create_payload(category="공지"), headers=HEADERS
    )
    assert resp.status_code == 200
    fake_channel.send.assert_not_called()

    post = asyncio.run(db.get_board_post(resp.json()["post_id"]))
    assert post["announced"] == 0


# ── 상세 조회 ──────────────────────────────────────────────

def test_get_post_detail_includes_comments_and_participants(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "자유", "내용", None))
    asyncio.run(db.add_board_comment(post_id, "222", "댓글"))
    asyncio.run(db.join_board_post(post_id, "222"))

    resp = client.get(f"/api/internal/board/posts/{post_id}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "글"
    assert len(body["comments"]) == 1
    assert len(body["participants"]) == 1


def test_get_post_detail_missing_returns_none(client, fake_bot):
    resp = client.get("/api/internal/board/posts/999", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() is None


# ── 수정/삭제 (작성자 전용) ─────────────────────────────────

def test_update_post_by_author_succeeds(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "원제목", "자유", "원내용", None))
    resp = client.patch(
        f"/api/internal/board/posts/{post_id}",
        json={"discord_id": "111", "title": "새제목", "content": "새내용", "scheduled_datetime": None},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    post = asyncio.run(db.get_board_post(post_id))
    assert post["title"] == "새제목"


def test_update_post_by_non_author_rejected(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "원제목", "자유", "원내용", None))
    resp = client.patch(
        f"/api/internal/board/posts/{post_id}",
        json={"discord_id": "222", "title": "해킹", "content": "해킹", "scheduled_datetime": None},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    post = asyncio.run(db.get_board_post(post_id))
    assert post["title"] == "원제목"


def test_delete_post_by_author_succeeds(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "자유", "내용", None))
    resp = client.request(
        "DELETE", f"/api/internal/board/posts/{post_id}",
        json={"discord_id": "111"}, headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert asyncio.run(db.get_board_post(post_id)) is None


def test_delete_post_by_non_author_rejected(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "자유", "내용", None))
    resp = client.request(
        "DELETE", f"/api/internal/board/posts/{post_id}",
        json={"discord_id": "222"}, headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert asyncio.run(db.get_board_post(post_id)) is not None


# ── 댓글/참여 ──────────────────────────────────────────────

def test_add_comment(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "자유", "내용", None))
    resp = client.post(
        f"/api/internal/board/posts/{post_id}/comments",
        json={"discord_id": "222", "content": "좋은 정보 감사합니다"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    comments = asyncio.run(db.list_board_comments(post_id))
    assert len(comments) == 1


def test_add_comment_rejects_empty_content(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "자유", "내용", None))
    resp = client.post(
        f"/api/internal/board/posts/{post_id}/comments",
        json={"discord_id": "222", "content": "   "},
        headers=HEADERS,
    )
    assert resp.json()["success"] is False


def test_join_and_leave_post(client, fake_bot):
    post_id = asyncio.run(db.create_board_post("1", "111", "글", "이벤트", "내용", None))

    join_resp = client.post(
        f"/api/internal/board/posts/{post_id}/join", json={"discord_id": "222"}, headers=HEADERS
    )
    assert join_resp.json()["success"] is True
    participants = asyncio.run(db.list_board_participants(post_id))
    assert len(participants) == 1

    leave_resp = client.post(
        f"/api/internal/board/posts/{post_id}/leave", json={"discord_id": "222"}, headers=HEADERS
    )
    assert leave_resp.json()["success"] is True
    assert asyncio.run(db.list_board_participants(post_id)) == []


def test_join_missing_post_returns_error(client, fake_bot):
    resp = client.post(
        "/api/internal/board/posts/999/join", json={"discord_id": "222"}, headers=HEADERS
    )
    assert resp.json()["success"] is False


# ── 게시판 설정 ────────────────────────────────────────────

def test_set_board_settings(client, fake_bot):
    resp = client.post(
        "/api/internal/board/settings",
        json={"guild_id": "1", "channel_id": "555", "role_id": "777"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    settings = asyncio.run(db.get_board_settings("1"))
    assert settings == {"board_channel_id": "555", "board_role_id": "777"}


def test_endpoints_require_webapp_key(client, fake_bot):
    resp = client.get("/api/internal/board/posts", params={"guild_id": "1"})
    assert resp.status_code in (401, 403, 422)
