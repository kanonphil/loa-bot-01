"""chat.py 라우트가 봇 서버 캐릭터 정보 + 대화 이력을 실제로 Gemini 호출에 넘기는지 검증.
Gemini 자체는 monkeypatch로 대체, 봇 서버 API는 respx로 모킹.
"""
import httpx
import respx

from webapp.tests.conftest import USER_CHARACTERS_URL, VERIFY_URL, log_in


def test_character_info_and_history_passed_to_gemini(client, monkeypatch):
    captured = {}

    async def _capturing_generate_reply(characters, history, new_message):
        captured["characters"] = characters
        captured["history"] = history
        captured["new_message"] = new_message
        return "캡처됨"

    monkeypatch.setattr(
        "webapp.routes.chat.generate_reply", _capturing_generate_reply
    )

    with respx.mock:
        login_resp = client.get("/login")
        from urllib.parse import parse_qs, urlparse

        state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

        respx.post("https://discord.com/api/v10/oauth2/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fake-token"})
        )
        respx.get("https://discord.com/api/v10/users/@me").mock(
            return_value=httpx.Response(200, json={"id": "111", "username": "tester"})
        )
        respx.get(VERIFY_URL).mock(
            return_value=httpx.Response(200, json={"discord_id": "111", "registered": True})
        )
        respx.get(USER_CHARACTERS_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"character_name": "발키리", "character_class": "서포터", "item_level": 1680.0}],
            )
        )
        client.get("/callback", params={"code": "abc", "state": state})

        # 첫 메시지 — 새 세션, history는 비어있어야 함
        create_resp = client.post("/chat/send", data={"message": "세팅 알려줘"})
        session_id = create_resp.headers["hx-redirect"].split("/")[-1]

        assert captured["characters"] == [
            {"character_name": "발키리", "character_class": "서포터", "item_level": 1680.0}
        ]
        assert captured["history"] == []
        assert captured["new_message"] == "세팅 알려줘"

        # 두 번째 메시지 — 이제 history에 첫 턴(유저 질문 + AI 응답)이 들어있어야 함
        client.post(
            "/chat/send", data={"message": "그럼 각인은?", "session_id": session_id}
        )

        history_roles_and_content = [
            {"role": m["role"], "content": m["content"]} for m in captured["history"]
        ]
        assert history_roles_and_content == [
            {"role": "user", "content": "세팅 알려줘"},
            {"role": "ai", "content": "캡처됨"},
        ]
        assert captured["new_message"] == "그럼 각인은?"


def test_bot_server_character_fetch_failure_falls_back_gracefully(client, monkeypatch):
    """봇 서버 호출이 실패해도(예: 다운) AI 상담 자체는 죽지 않고 캐릭터 정보 없이 진행."""

    async def _capturing_generate_reply(characters, history, new_message):
        return f"characters={characters!r}"

    monkeypatch.setattr(
        "webapp.routes.chat.generate_reply", _capturing_generate_reply
    )

    with respx.mock:
        login_resp = client.get("/login")
        from urllib.parse import parse_qs, urlparse

        state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

        respx.post("https://discord.com/api/v10/oauth2/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fake-token"})
        )
        respx.get("https://discord.com/api/v10/users/@me").mock(
            return_value=httpx.Response(200, json={"id": "111", "username": "tester"})
        )
        respx.get(VERIFY_URL).mock(
            return_value=httpx.Response(200, json={"discord_id": "111", "registered": True})
        )
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(500))
        client.get("/callback", params={"code": "abc", "state": state})

        resp = client.post("/chat/send", data={"message": "세팅 알려줘"})

    assert resp.status_code == 200
    assert "hx-redirect" in resp.headers
