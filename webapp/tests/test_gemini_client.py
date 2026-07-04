"""webapp.ai.gemini_client 단위 테스트 — 실제 SDK 클라이언트는 목으로 대체."""
import os

os.environ.setdefault("DISCORD_CLIENT_ID", "test-client-id")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("BOT_API_WEBAPP_KEY", "test-webapp-key")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import errors

from webapp import config
from webapp.ai import gemini_client
from webapp.ai.gemini_client import GeminiError, generate_reply


@pytest.fixture(autouse=True)
def _reset_client_singleton(monkeypatch):
    # 모듈 전역 _client 캐시가 테스트 간에 새 나가지 않도록 매번 리셋
    monkeypatch.setattr(gemini_client, "_client", None)


@pytest.fixture()
def has_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-gemini-key")


def _fake_client(response=None, side_effect=None):
    generate = AsyncMock()
    if side_effect is not None:
        generate.side_effect = side_effect
    else:
        generate.return_value = response
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))), generate


def test_no_api_key_raises_gemini_error_without_network_call(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    with pytest.raises(GeminiError):
        __import__("asyncio").run(generate_reply([], [], "질문"))


def test_successful_reply_returns_text(monkeypatch, has_api_key):
    fake_client, generate = _fake_client(response=SimpleNamespace(text="답변입니다"))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    import asyncio

    result = asyncio.run(generate_reply([], [], "질문"))
    assert result == "답변입니다"


def test_character_context_included_in_system_instruction(monkeypatch, has_api_key):
    fake_client, generate = _fake_client(response=SimpleNamespace(text="답변"))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    characters = [
        {"character_name": "발키리", "character_class": "서포터", "item_level": 1680.0}
    ]

    import asyncio

    asyncio.run(generate_reply(characters, [], "세팅 알려줘"))

    _, kwargs = generate.call_args
    system_instruction = kwargs["config"].system_instruction
    assert "발키리" in system_instruction
    assert "서포터" in system_instruction
    assert "1680.0" in system_instruction


def test_no_characters_notes_that_in_system_instruction(monkeypatch, has_api_key):
    fake_client, generate = _fake_client(response=SimpleNamespace(text="답변"))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    import asyncio

    asyncio.run(generate_reply([], [], "질문"))

    _, kwargs = generate.call_args
    assert "등록되어 있지 않습니다" in kwargs["config"].system_instruction


def test_history_is_translated_to_gemini_roles(monkeypatch, has_api_key):
    fake_client, generate = _fake_client(response=SimpleNamespace(text="답변"))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    history = [
        {"role": "user", "content": "이전 질문"},
        {"role": "ai", "content": "이전 답변"},
    ]

    import asyncio

    asyncio.run(generate_reply([], history, "새 질문"))

    _, kwargs = generate.call_args
    contents = kwargs["contents"]
    assert contents[0] == {"role": "user", "parts": [{"text": "이전 질문"}]}
    assert contents[1] == {"role": "model", "parts": [{"text": "이전 답변"}]}
    assert contents[2] == {"role": "user", "parts": [{"text": "새 질문"}]}


def test_api_error_raises_gemini_error(monkeypatch, has_api_key):
    def _raise(*args, **kwargs):
        raise errors.ClientError(429, {"error": {"message": "rate limited"}})

    fake_client, generate = _fake_client(side_effect=_raise)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    import asyncio

    with pytest.raises(GeminiError):
        asyncio.run(generate_reply([], [], "질문"))


def test_empty_response_text_raises_gemini_error(monkeypatch, has_api_key):
    fake_client, generate = _fake_client(response=SimpleNamespace(text=""))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)

    import asyncio

    with pytest.raises(GeminiError):
        asyncio.run(generate_reply([], [], "질문"))
