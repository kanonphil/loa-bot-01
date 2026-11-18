"""webapp/clients/bot_exp.py — 봇 엔드포인트가 없거나 느려도 예외 없이 None/실패 값으로 돌려주는지."""
import asyncio

import httpx
import pytest
import respx

from webapp.clients import bot_exp

B = "http://bot-server.internal/api/internal"


@pytest.fixture(autouse=True)
def _fresh_client():
    """asyncio.run마다 이벤트 루프가 새로 생기므로, 공유 httpx 클라이언트가 닫힌 루프에 묶여 다른 테스트로 새지 않게 한다."""
    from webapp.clients import bot_client

    bot_client._client = None
    yield
    bot_client._client = None


def _run(coro):
    return asyncio.run(coro)


def test_history_sorted_and_filtered():
    with respx.mock:
        respx.get(f"{B}/characters/%EB%B0%9C/history").mock(return_value=httpx.Response(200, json={"items": [
            {"date": "2026-11-03", "combat_power": 3}, {"date": "2026-11-01", "combat_power": 1}, {"combat_power": 9}, "junk"]}))
        items = _run(bot_exp.get_character_history("1", "발", 90))
    assert [i["date"] for i in items] == ["2026-11-01", "2026-11-03"]


def test_get_helpers_return_none_on_404_timeout_and_bad_json():
    with respx.mock:
        respx.get(f"{B}/loa/prices").mock(return_value=httpx.Response(404))
        assert _run(bot_exp.get_loa_prices()) is None
        respx.get(f"{B}/loa/overview").mock(side_effect=httpx.ReadTimeout("slow"))
        assert _run(bot_exp.get_loa_overview("1")) is None
        respx.get(f"{B}/characters/a/history").mock(return_value=httpx.Response(200, json=[1, 2]))
        assert _run(bot_exp.get_character_history("1", "a")) is None


def test_gold_subscription_failure_shapes():
    with respx.mock:
        respx.post(f"{B}/loa/gold-island-subscription").mock(return_value=httpx.Response(404))
        r = _run(bot_exp.set_gold_island_subscription("1", True))
        assert r["success"] is False and "지원하지 않습니다" in r["reason"]
        respx.post(f"{B}/loa/gold-island-subscription").mock(side_effect=httpx.ConnectError("down"))
        assert _run(bot_exp.set_gold_island_subscription("1", True))["success"] is False
