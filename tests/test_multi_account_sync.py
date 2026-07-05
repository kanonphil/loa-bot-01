"""bot/services/expedition.py — 다중 계정(부계정) 캐릭터 자동 판별/그룹 동기화 검증.
Discord 버튼(ExpeditionView), 웹 API(internal.py), 일일 자동 동기화 태스크가
모두 이 모듈의 함수를 공유하므로, 여기서 핵심 로직만 검증하면 충분하다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.database.manager as db
import bot.services.expedition as svc

ACCOUNT_A_SIBLINGS = [
    {"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"},
    {"CharacterName": "워로드부캐", "CharacterClassName": "워로드", "ItemMaxLevel": "1,700.00"},
]
ACCOUNT_B_SIBLINGS = [
    {"CharacterName": "슬레이어", "CharacterClassName": "슬레이어", "ItemMaxLevel": "1,690.00"},
]


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def _make_fake_get_siblings(mapping: dict[str, list[dict]]):
    """api_key -> siblings 매핑으로 가짜 get_siblings 생성."""
    async def fake(api_key, name):
        return mapping.get(api_key)
    return fake


def test_resolve_character_account_tries_each_key_in_order(clean_db, monkeypatch):
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("111", "슬레이어", "key-b"))

    fake = _make_fake_get_siblings({"key-a": ACCOUNT_A_SIBLINGS, "key-b": ACCOUNT_B_SIBLINGS})
    monkeypatch.setattr(svc.loa, "get_siblings", fake)

    char, key_id, error = asyncio.run(svc.resolve_character_account("111", "슬레이어"))
    assert error is None
    assert key_id == id_b
    assert char["CharacterName"] == "슬레이어"


def test_resolve_character_account_not_found_in_any_account(clean_db, monkeypatch):
    asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    asyncio.run(db.add_user_api_key("111", "슬레이어", "key-b"))

    fake = _make_fake_get_siblings({"key-a": ACCOUNT_A_SIBLINGS, "key-b": ACCOUNT_B_SIBLINGS})
    monkeypatch.setattr(svc.loa, "get_siblings", fake)

    char, key_id, error = asyncio.run(svc.resolve_character_account("111", "없는캐릭터"))
    assert char is None
    assert key_id is None
    assert "찾을 수 없습니다" in error


def test_register_character_auto_detect_second_account(clean_db, monkeypatch):
    """계정이 2개 등록된 유저가, 두 번째 계정 소속 캐릭터를 등록하는 경우도
    정상적으로 그 계정에 연결되어 저장돼야 한다."""
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("111", "슬레이어", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id_a))

    fake = _make_fake_get_siblings({"key-a": ACCOUNT_A_SIBLINGS, "key-b": ACCOUNT_B_SIBLINGS})
    monkeypatch.setattr(svc.loa, "get_siblings", fake)

    result = asyncio.run(svc.register_character_auto_detect("111", "슬레이어"))
    assert result["success"] is True
    assert result["character_class"] == "슬레이어"

    chars_under_b = asyncio.run(db.get_characters_by_api_key_id(id_b))
    assert chars_under_b == ["슬레이어"]


def test_register_character_auto_detect_no_matching_account(clean_db, monkeypatch):
    asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))

    fake = _make_fake_get_siblings({"key-a": ACCOUNT_A_SIBLINGS})
    monkeypatch.setattr(svc.loa, "get_siblings", fake)

    result = asyncio.run(svc.register_character_auto_detect("111", "남의캐릭터"))
    assert result["success"] is False
    assert "찾을 수 없습니다" in result["reason"]


def test_sync_characters_for_discord_id_groups_by_account(clean_db, monkeypatch):
    """계정 2개, 각각 다른 캐릭터를 가진 유저의 동기화 — 각 캐릭터가 자기 계정의
    siblings 데이터로만 갱신돼야 하고, 다른 계정 캐릭터가 섞이면 안 된다."""
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("111", "슬레이어", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id_a))
    asyncio.run(db.add_character("111", "워로드부캐", api_key_id=id_a))
    asyncio.run(db.add_character("111", "슬레이어", api_key_id=id_b))

    calls = []

    async def fake_get_siblings(api_key, name):
        calls.append((api_key, name))
        return {"key-a": ACCOUNT_A_SIBLINGS, "key-b": ACCOUNT_B_SIBLINGS}.get(api_key)

    monkeypatch.setattr(svc.loa, "get_siblings", fake_get_siblings)

    updated, total = asyncio.run(svc.sync_characters_for_discord_id("111"))

    assert total == 3
    assert updated == 3

    cached = asyncio.run(db.get_cached_characters("111", max_age_hours=99999))
    levels = {c["character_name"]: c["item_level"] for c in cached}
    assert levels["발키리"] == 1720.0
    assert levels["워로드부캐"] == 1700.0
    assert levels["슬레이어"] == 1690.0

    # 계정별로 get_siblings가 딱 1번씩만 호출됐어야 한다 (캐릭터 수만큼이 아니라 계정 수만큼)
    assert len(calls) == 2
    called_keys = {c[0] for c in calls}
    assert called_keys == {"key-a", "key-b"}


def test_sync_characters_for_discord_id_no_accounts(clean_db):
    asyncio.run(db.add_character("111", "무계정캐릭"))
    updated, total = asyncio.run(svc.sync_characters_for_discord_id("111"))
    assert (updated, total) == (0, 1)


def test_sync_characters_for_discord_id_no_characters(clean_db):
    asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    updated, total = asyncio.run(svc.sync_characters_for_discord_id("111"))
    assert (updated, total) == (0, 0)


def test_sync_all_accounts_daily_continues_after_one_account_fails(clean_db, monkeypatch):
    """한 계정에서 예외가 나도(만료된 키 등) 다른 계정 처리는 계속돼야 한다."""
    id_a = asyncio.run(db.add_user_api_key("111", "발키리", "key-a"))
    id_b = asyncio.run(db.add_user_api_key("222", "슬레이어", "key-b"))
    asyncio.run(db.add_character("111", "발키리", api_key_id=id_a))
    asyncio.run(db.add_character("222", "슬레이어", api_key_id=id_b))

    async def flaky_get_siblings(api_key, name):
        if api_key == "key-a":
            raise RuntimeError("API 키가 유효하지 않습니다.")
        return ACCOUNT_B_SIBLINGS

    monkeypatch.setattr(svc.loa, "get_siblings", flaky_get_siblings)

    async def no_sleep(_):
        return None
    monkeypatch.setattr(svc.asyncio, "sleep", no_sleep)

    asyncio.run(svc.sync_all_accounts_daily())

    cached_222 = asyncio.run(db.get_cached_characters("222", max_age_hours=99999))
    levels = {c["character_name"]: c["item_level"] for c in cached_222}
    assert levels["슬레이어"] == 1690.0

    # 실패한 계정(111)의 캐릭터는 갱신되지 않았지만 예외가 전파되지 않았어야 한다
    cached_111 = asyncio.run(db.get_cached_characters("111", max_age_hours=99999))
    assert cached_111[0]["item_level"] is None
