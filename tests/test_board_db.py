"""bot/database/manager.py의 길드 커뮤니티 게시판 함수 검증.

시간 비교가 들어가는 리마인더 조회는 datetime.now()에 기대지 않고, scheduled_datetime과
now_iso 둘 다 테스트에서 고정된 문자열로 넘겨 결정론적으로 검증한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import asyncio

import pytest

import bot.database.manager as db

GUILD_ID = "1"
AUTHOR = "111"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    asyncio.run(db.init_db())
    return path


# ── 게시글 CRUD ────────────────────────────────────────────

def test_create_and_get_post(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "길드 회식", "이벤트", "다같이 모입시다", "2026-08-01T20:00:00+09:00")
    )
    post = asyncio.run(db.get_board_post(post_id))
    assert post["title"] == "길드 회식"
    assert post["category"] == "이벤트"
    assert post["announced"] == 0
    assert post["reminder_10min_sent"] == 0
    assert post["reminder_start_sent"] == 0


def test_create_post_without_schedule_for_notice(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "공지사항", "공지", "점검 예정", None)
    )
    post = asyncio.run(db.get_board_post(post_id))
    assert post["scheduled_datetime"] is None


def test_get_missing_post_returns_none(db_path):
    assert asyncio.run(db.get_board_post(999)) is None


def test_list_posts_newest_first(db_path):
    p1 = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "첫번째", "자유", "내용1", None))
    p2 = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "두번째", "자유", "내용2", None))
    posts = asyncio.run(db.list_board_posts(GUILD_ID))
    assert [p["id"] for p in posts] == [p2, p1]


def test_list_posts_filters_by_category(db_path):
    asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "이벤트글", "이벤트", "내용", None))
    asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "공지글", "공지", "내용", None))
    events = asyncio.run(db.list_board_posts(GUILD_ID, category="이벤트"))
    assert len(events) == 1
    assert events[0]["title"] == "이벤트글"


def test_list_posts_scoped_to_guild(db_path):
    asyncio.run(db.create_board_post("1", AUTHOR, "길드1", "자유", "내용", None))
    asyncio.run(db.create_board_post("2", AUTHOR, "길드2", "자유", "내용", None))
    posts = asyncio.run(db.list_board_posts("1"))
    assert len(posts) == 1
    assert posts[0]["title"] == "길드1"


def test_update_post_changes_fields(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "원제목", "자유", "원내용", None))
    updated = asyncio.run(db.update_board_post(post_id, "새제목", "새내용", "2026-08-01T20:00:00+09:00"))
    assert updated is True
    post = asyncio.run(db.get_board_post(post_id))
    assert post["title"] == "새제목"
    assert post["content"] == "새내용"
    assert post["scheduled_datetime"] == "2026-08-01T20:00:00+09:00"


def test_update_missing_post_returns_false(db_path):
    assert asyncio.run(db.update_board_post(999, "제목", "내용", None)) is False


def test_delete_post_cascades_comments_and_participants(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "삭제될 글", "자유", "내용", None))
    asyncio.run(db.add_board_comment(post_id, "222", "댓글"))
    asyncio.run(db.join_board_post(post_id, "222"))

    deleted = asyncio.run(db.delete_board_post(post_id))
    assert deleted is True
    assert asyncio.run(db.get_board_post(post_id)) is None
    assert asyncio.run(db.list_board_comments(post_id)) == []
    assert asyncio.run(db.list_board_participants(post_id)) == []


def test_delete_missing_post_returns_false(db_path):
    assert asyncio.run(db.delete_board_post(999)) is False


# ── 댓글 ──────────────────────────────────────────────────

def test_comments_listed_oldest_first(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글", "자유", "내용", None))
    asyncio.run(db.add_board_comment(post_id, "222", "먼저 씀"))
    asyncio.run(db.add_board_comment(post_id, "333", "나중에 씀"))

    comments = asyncio.run(db.list_board_comments(post_id))
    assert [c["content"] for c in comments] == ["먼저 씀", "나중에 씀"]


def test_comments_scoped_to_post(db_path):
    p1 = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글1", "자유", "내용", None))
    p2 = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글2", "자유", "내용", None))
    asyncio.run(db.add_board_comment(p1, "222", "글1 댓글"))
    asyncio.run(db.add_board_comment(p2, "222", "글2 댓글"))

    assert len(asyncio.run(db.list_board_comments(p1))) == 1
    assert len(asyncio.run(db.list_board_comments(p2))) == 1


# ── 참여 (join/leave) ──────────────────────────────────────

def test_join_is_idempotent(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글", "이벤트", "내용", None))
    first = asyncio.run(db.join_board_post(post_id, "222"))
    second = asyncio.run(db.join_board_post(post_id, "222"))
    assert first is True
    assert second is False  # 이미 참여 중이므로 새로 삽입되지 않음

    participants = asyncio.run(db.list_board_participants(post_id))
    assert len(participants) == 1


def test_leave_removes_participant(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글", "이벤트", "내용", None))
    asyncio.run(db.join_board_post(post_id, "222"))
    left = asyncio.run(db.leave_board_post(post_id, "222"))
    assert left is True
    assert asyncio.run(db.list_board_participants(post_id)) == []


def test_leave_when_not_joined_returns_false(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글", "이벤트", "내용", None))
    assert asyncio.run(db.leave_board_post(post_id, "222")) is False


def test_participants_listed_join_order(db_path):
    post_id = asyncio.run(db.create_board_post(GUILD_ID, AUTHOR, "글", "이벤트", "내용", None))
    asyncio.run(db.join_board_post(post_id, "222"))
    asyncio.run(db.join_board_post(post_id, "333"))
    participants = asyncio.run(db.list_board_participants(post_id))
    assert [p["discord_id"] for p in participants] == ["222", "333"]


# ── 리마인더 조회 (시간은 항상 명시적 ISO 문자열로 고정) ─────────

def test_10min_reminder_due_when_within_window(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    # 시작 10분 전 = 19:50 — 지금이 19:51이면 이미 지남 → 발송 대상
    due = asyncio.run(db.get_posts_due_10min_reminder("2026-08-01T19:51:00+09:00"))
    assert [p["id"] for p in due] == [post_id]


def test_10min_reminder_not_due_before_window(db_path):
    asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    # 지금이 19:00이면 10분 전 시각(19:50)에 아직 도달 안 함
    due = asyncio.run(db.get_posts_due_10min_reminder("2026-08-01T19:00:00+09:00"))
    assert due == []


def test_10min_reminder_excludes_non_event_category(db_path):
    asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "공지", "공지", "내용", "2026-08-01T20:00:00+09:00")
    )
    due = asyncio.run(db.get_posts_due_10min_reminder("2026-08-01T19:59:00+09:00"))
    assert due == []


def test_10min_reminder_excludes_already_sent(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    asyncio.run(db.mark_board_reminder_sent(post_id, "10min"))
    due = asyncio.run(db.get_posts_due_10min_reminder("2026-08-01T19:51:00+09:00"))
    assert due == []


def test_start_reminder_due_at_scheduled_time(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    due = asyncio.run(db.get_posts_due_start_reminder("2026-08-01T20:00:00+09:00"))
    assert [p["id"] for p in due] == [post_id]


def test_start_reminder_not_due_before_scheduled_time(db_path):
    asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    due = asyncio.run(db.get_posts_due_start_reminder("2026-08-01T19:59:59+09:00"))
    assert due == []


def test_start_reminder_excludes_already_sent(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    asyncio.run(db.mark_board_reminder_sent(post_id, "start"))
    due = asyncio.run(db.get_posts_due_start_reminder("2026-08-01T20:00:00+09:00"))
    assert due == []


def test_mark_board_announced(db_path):
    post_id = asyncio.run(
        db.create_board_post(GUILD_ID, AUTHOR, "이벤트", "이벤트", "내용", "2026-08-01T20:00:00+09:00")
    )
    asyncio.run(db.mark_board_announced(post_id))
    post = asyncio.run(db.get_board_post(post_id))
    assert post["announced"] == 1


# ── 서버 설정 ──────────────────────────────────────────────

def test_set_and_get_board_settings(db_path):
    asyncio.run(db.set_board_channel(GUILD_ID, "999", "888"))
    settings = asyncio.run(db.get_board_settings(GUILD_ID))
    assert settings == {"board_channel_id": "999", "board_role_id": "888"}


def test_get_board_settings_returns_none_when_unset(db_path):
    assert asyncio.run(db.get_board_settings("no-such-guild")) is None


def test_set_board_channel_does_not_clobber_forum_channel(db_path):
    """guild_settings는 forum_channel_id와 board_channel_id를 공유하는 단일 row —
    게시판 채널을 나중에 설정해도 기존 포럼 채널 설정이 지워지면 안 된다."""
    asyncio.run(db.set_forum_channel(GUILD_ID, "111"))
    asyncio.run(db.set_board_channel(GUILD_ID, "999", "888"))
    assert asyncio.run(db.get_forum_channel_id(GUILD_ID)) == "111"
    assert asyncio.run(db.get_board_settings(GUILD_ID)) == {"board_channel_id": "999", "board_role_id": "888"}
