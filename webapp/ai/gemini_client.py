"""Gemini API 연동 — 캐릭터 세팅 상담용 단일 호출.
매 요청마다 캐릭터 정보 + 이전 대화 이력을 프롬프트에 넣어 Gemini를 1회 호출한다.
"""
from google import genai
from google.genai import errors, types

from webapp import config

SYSTEM_PROMPT = (
    "당신은 로스트아크 길드 전용 AI 상담원입니다. "
    "길드원의 캐릭터 세팅(직업, 아이템레벨, 각인, 보석, 장신구)에 대한 질문에 답합니다. "
    "정확히 모르는 내용은 추측으로 단정짓지 말고 모른다고 솔직히 답하세요. "
    "답변은 한국어로 간결하고 실용적으로 작성하세요."
)


class GeminiError(Exception):
    """AI 응답을 만들지 못했을 때. 호출 측에서 사용자용 안내 메시지로 변환한다."""


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _character_context(characters: list[dict]) -> str:
    if not characters:
        return "이 유저는 아직 로스트아크 캐릭터가 등록되어 있지 않습니다."
    lines = [
        f"- {c.get('character_name')} ({c.get('character_class')}, "
        f"아이템레벨 {c.get('item_level')})"
        for c in characters
    ]
    return "등록된 캐릭터:\n" + "\n".join(lines)


def _build_contents(history: list[dict], new_message: str) -> list[dict]:
    contents = [
        {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
        for m in history
    ]
    contents.append({"role": "user", "parts": [{"text": new_message}]})
    return contents


async def generate_reply(characters: list[dict], history: list[dict], new_message: str) -> str:
    if not config.GEMINI_API_KEY:
        raise GeminiError("Gemini API 키가 설정되지 않았습니다.")

    system_instruction = f"{SYSTEM_PROMPT}\n\n{_character_context(characters)}"
    contents = _build_contents(history, new_message)

    try:
        response = await _get_client().aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(systemInstruction=system_instruction),
        )
    except errors.APIError as e:
        raise GeminiError(f"Gemini API 오류: {e}") from e

    text = getattr(response, "text", None)
    if not text:
        raise GeminiError("Gemini가 빈 응답을 반환했습니다.")
    return text
