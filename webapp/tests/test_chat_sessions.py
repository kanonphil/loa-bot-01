"""새 채팅 시작 -> 세션 생성 -> 리다이렉트 -> 이어가기 흐름 + 세션 소유권 검증.
AI 응답 자체(Gemini 연동)는 test_gemini_client.py / test_chat_ai_integration.py가 담당하고,
여기서는 mock_ai_reply로 고정 응답을 넣어 세션 흐름만 검증한다.
"""
import respx

from webapp.tests.conftest import STUB_AI_REPLY, log_in


def test_new_message_without_session_creates_session_and_redirects(client, mock_ai_reply):
    with respx.mock:
        log_in(client)
        resp = client.post("/chat/send", data={"message": "블레이드 세팅 알려줘"})

    assert resp.status_code == 200
    assert "hx-redirect" in resp.headers  # HX-Redirect (대소문자 구분 없이 비교됨)
    location = resp.headers["hx-redirect"]
    assert location.startswith("/chat/")


def test_redirected_thread_shows_first_turn_and_sidebar_entry(client, mock_ai_reply):
    with respx.mock:
        log_in(client)
        create_resp = client.post("/chat/send", data={"message": "블레이드 세팅 알려줘"})
        session_url = create_resp.headers["hx-redirect"]

        thread_resp = client.get(session_url)

    assert thread_resp.status_code == 200
    body = thread_resp.text
    assert "블레이드 세팅 알려줘" in body
    assert STUB_AI_REPLY in body
    # 사이드바 최근 목록에도 같은 세션이 링크로 떠야 함
    assert session_url in body
    # 이어지는 대화 화면에도 AI 상담 한계 공지가 보여야 함
    assert 'class="ai-notice' in body


def test_continuing_thread_appends_without_redirect(client, mock_ai_reply):
    with respx.mock:
        log_in(client)
        create_resp = client.post("/chat/send", data={"message": "첫 질문"})
        session_id = create_resp.headers["hx-redirect"].split("/")[-1]

        follow_up = client.post(
            "/chat/send", data={"message": "두 번째 질문", "session_id": session_id}
        )

    assert follow_up.status_code == 200
    assert "hx-redirect" not in follow_up.headers
    assert "두 번째 질문" in follow_up.text


def test_cannot_view_another_users_session(client, mock_ai_reply):
    with respx.mock:
        log_in(client, discord_id="111")
        create_resp = client.post("/chat/send", data={"message": "111의 비밀 질문"})
        session_url = create_resp.headers["hx-redirect"]

        # 다른 유저로 재로그인 (세션 쿠키가 새 유저로 덮어써짐)
        log_in(client, discord_id="222")
        resp = client.get(session_url)

    assert resp.status_code == 404


def test_cannot_post_to_another_users_session(client, mock_ai_reply):
    with respx.mock:
        log_in(client, discord_id="111")
        create_resp = client.post("/chat/send", data={"message": "111의 세션"})
        session_id = create_resp.headers["hx-redirect"].split("/")[-1]

        log_in(client, discord_id="222")
        resp = client.post(
            "/chat/send", data={"message": "가로채기 시도", "session_id": session_id}
        )

    assert resp.status_code == 404
