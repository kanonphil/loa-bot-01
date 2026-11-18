"""로스트아크 공용 데이터(bot/services/loa_content.py)와 /loa/* 엔드포인트 검증.

로스트아크 HTTP는 전부 가짜 aiohttp 세션으로 대체한다(실제 호출 없음)."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import bot.api.lostark as loa
import bot.data.raids as raids_module
import bot.database.manager as db
import config
from bot.services import loa_content

KST = timezone(timedelta(hours=9))
HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "111"
SERVER_OWNER = "999"
ME = "555"


class FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload

    async def text(self):
        return str(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """routes: {(METHOD, path): (status, payload, headers) 또는 callable(json_body)->tuple}"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.closed = False

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        path = url.replace(loa.LOA_API_BASE, "")
        self.calls.append((method, path, params, json))
        route = self.routes.get((method, path))
        if route is None:
            return FakeResp(404, None)
        if callable(route):
            route = route(params, json)
        status, payload, *rest = route
        return FakeResp(status, payload, rest[0] if rest else None)


def _install(monkeypatch, routes) -> FakeSession:
    session = FakeSession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(loa, "_get_session", fake_get_session)
    return session


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", SERVER_OWNER)
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(SERVER_OWNER, "server-key"))
    loa_content._reset_state_for_tests()
    loa._rate_state.clear()
    yield
    loa_content._reset_state_for_tests()
    loa._rate_state.clear()


@pytest.fixture()
def client(env):
    from bot.api.server import app

    return TestClient(app)


NOW = datetime(2026, 11, 19, 20, 0, tzinfo=KST)  # 목요일 20:00

CALENDAR = [
    {   # 현행 모양 — RewardItems[].Items[], 보상별 StartTimes
        "CategoryName": "모험 섬",
        "ContentsName": "메데이아",
        "ContentsIcon": "https://img/medeia.png",
        "MinItemLevel": 1415,
        "StartTimes": ["2026-11-19T21:00:00", "2026-11-19T23:00:00", "2026-11-20T11:00:00"],
        "RewardItems": [{"ItemLevel": 1415, "Items": [
            {"Name": "골드", "Icon": "gold.png", "Grade": "일반", "StartTimes": ["2026-11-19T21:00:00", "2026-11-19T23:00:00"]},
            {"Name": "실링", "Icon": "silling.png", "Grade": "일반", "StartTimes": ["2026-11-20T11:00:00"]},
            {"Name": "카드 팩", "Icon": "card.png", "Grade": "영웅", "StartTimes": None},
        ]}],
    },
    {   # 구버전 모양 — RewardItems가 아이템 목록 그대로
        "CategoryName": "모험 섬",
        "ContentsName": "볼라르 섬",
        "ContentsIcon": "https://img/volar.png",
        "MinItemLevel": 1415,
        "StartTimes": ["2026-11-19T19:00:00"],
        "RewardItems": [{"Name": "해적 주화", "Icon": "coin.png", "Grade": "일반", "StartTimes": None}],
    },
    {
        "CategoryName": "필드보스",
        "ContentsName": "세베크 아툰",
        "ContentsIcon": None,
        "MinItemLevel": "1,460",
        "StartTimes": ["2026-11-19T22:00:00"],
        "RewardItems": [{"ItemLevel": 1460, "Items": [{"Name": "골드", "StartTimes": None}]}],
    },
    {"CategoryName": "로웬", "ContentsName": "상시", "StartTimes": None, "RewardItems": None},
    "깨진 항목",
]

NOTICES = [
    {"Title": "11월 19일(수) 정기 점검 안내 (06:00 ~ 10:00)", "Date": "2026-11-18T15:00:00",
     "Link": "https://lostark/notice/1", "Type": "점검"},
    {"Title": "상점 업데이트", "Date": "2026-11-19T10:00:00", "Link": "https://lostark/notice/2", "Type": "상점"},
]
EVENTS = [
    {"Title": "겨울 이벤트", "Thumbnail": "t.png", "Link": "https://lostark/ev/1",
     "StartDate": "2026-11-12T10:00:00", "EndDate": "2026-12-10T06:00:00"},
    {"Title": "끝난 이벤트", "Thumbnail": "t2.png", "Link": "https://lostark/ev/2",
     "StartDate": "2026-10-01T10:00:00", "EndDate": "2026-11-01T06:00:00"},
]


def _content_routes():
    return {
        ("GET", "/news/notices"): lambda params, _j: (200, NOTICES if not params else [NOTICES[0]]),
        ("GET", "/news/events"): (200, EVENTS),
        ("GET", "/gamecontents/calendar"): (200, CALENDAR),
    }


# ── 순수 함수 ──────────────────────────────────────────────

def test_is_gold_island_matcher():
    assert loa_content.is_gold_island("모험 섬", ["실링", "골드"])
    assert loa_content.is_gold_island("모험 섬", ["골드 주머니"])
    assert not loa_content.is_gold_island("모험 섬", ["실링", "해적 주화"])
    assert not loa_content.is_gold_island("필드보스", ["골드"])
    assert not loa_content.is_gold_island("", [])


def test_items_for_date_filters_times_and_rewards_by_day():
    cal = loa_content.normalize_calendar(CALENDAR)
    assert len(cal) == 4  # 문자열 항목은 버린다
    today = loa_content.items_for_date(cal, "2026-11-19")
    names = [i["name"] for i in today]
    assert names == ["볼라르 섬", "메데이아", "세베크 아툰"]  # 첫 시각 순
    medeia = today[1]
    assert medeia["times"] == ["2026-11-19T21:00:00+09:00", "2026-11-19T23:00:00+09:00"]
    assert {r["name"] for r in medeia["rewards"]} == {"골드", "카드 팩"}
    assert medeia["is_gold"] is True
    assert today[0]["is_gold"] is False
    assert today[2]["is_gold"] is False  # 필드보스는 골드 보상이 있어도 골드 섬이 아니다
    assert today[2]["min_item_level"] == 1460

    tomorrow = loa_content.items_for_date(cal, "2026-11-20")
    assert [i["name"] for i in tomorrow] == ["메데이아"]
    assert tomorrow[0]["is_gold"] is False  # 그날 보상은 실링뿐
    assert {r["name"] for r in tomorrow[0]["rewards"]} == {"실링", "카드 팩"}


def test_first_gold_island():
    cal = loa_content.normalize_calendar(CALENDAR)
    start, names = loa_content.first_gold_island(cal, NOW)
    assert start == datetime(2026, 11, 19, 21, 0, tzinfo=KST)
    assert names == ["메데이아"]


def test_detect_maintenance_from_notice_title():
    notices = loa_content.parse_notices(NOTICES)
    wed_7am = datetime(2026, 11, 19, 7, 0, tzinfo=KST)
    m = loa_content.detect_maintenance(notices, wed_7am, outage=False)
    assert m["active"] is True
    assert m["starts_at"] == "2026-11-19T06:00:00+09:00"
    assert m["ends_at"] == "2026-11-19T10:00:00+09:00"
    assert m["link"] == "https://lostark/notice/1"

    before = loa_content.detect_maintenance(notices, datetime(2026, 11, 18, 20, 0, tzinfo=KST), outage=False)
    assert before["active"] is False  # 예정된 점검
    after = loa_content.detect_maintenance(notices, datetime(2026, 11, 20, 12, 0, tzinfo=KST), outage=False)
    assert after is None  # 지난 점검은 숨긴다

    outage = loa_content.detect_maintenance([], NOW, outage=True)
    assert outage == {"active": True, "title": "점검 중", "starts_at": None, "ends_at": None, "link": None}


def test_content_interval_is_shorter_in_wednesday_window():
    assert loa_content._content_interval(datetime(2026, 11, 18, 6, 0, tzinfo=KST)) == timedelta(minutes=5)
    assert loa_content._content_interval(datetime(2026, 11, 18, 10, 30, tzinfo=KST)) == timedelta(minutes=30)
    assert loa_content._content_interval(NOW) == timedelta(minutes=30)


# ── lostark.py: 한도/점검 ──────────────────────────────────

def test_rate_limit_backoff_waits_until_reset(env, monkeypatch):
    reset = 1_000_060.0
    session = _install(monkeypatch, {
        ("GET", "/news/events"): (200, [], {"X-RateLimit-Remaining": "5", "X-RateLimit-Reset": str(int(reset))}),
    })
    monkeypatch.setattr(loa.time, "time", lambda: 1_000_000.0)
    slept = []

    async def fake_sleep(sec):
        slept.append(sec)

    monkeypatch.setattr(loa.asyncio, "sleep", fake_sleep)
    asyncio.run(loa.get_events("k"))
    assert slept == []  # 첫 호출은 기다리지 않는다
    assert loa.rate_limit_wait_seconds("k") == 60.0
    asyncio.run(loa.get_events("k"))
    assert slept == [60.0]
    assert len(session.calls) == 2
    # 다른 키는 영향 없음
    assert loa.rate_limit_wait_seconds("other") == 0.0


def test_rate_limit_no_wait_when_plenty_remaining(env, monkeypatch):
    _install(monkeypatch, {("GET", "/news/events"): (200, [], {"X-RateLimit-Remaining": "50"})})
    asyncio.run(loa.get_events("k"))
    assert loa.rate_limit_wait_seconds("k") == 0.0


def test_503_raises_maintenance_error_subclass_of_runtime_error(env, monkeypatch):
    _install(monkeypatch, {("GET", "/news/events"): (503, "maintenance")})
    with pytest.raises(loa.LoaMaintenanceError):
        asyncio.run(loa.get_events("k"))
    assert issubclass(loa.LoaMaintenanceError, RuntimeError)


def test_post_sends_json_body(env, monkeypatch):
    session = _install(monkeypatch, {("POST", "/markets/items"): (200, {"Items": []})})
    asyncio.run(loa.search_market_items("k", "파괴석", 50000))
    method, path, _params, body = session.calls[0]
    assert (method, path) == ("POST", "/markets/items")
    assert body["ItemName"] == "파괴석" and body["CategoryCode"] == 50000 and body["PageNo"] == 1


# ── 수집과 스냅샷 ──────────────────────────────────────────

def test_refresh_content_and_overview(env, monkeypatch):
    _install(monkeypatch, _content_routes())
    assert asyncio.run(loa_content.refresh_content(NOW)) is True
    ov = asyncio.run(loa_content.overview(ME, NOW))
    assert ov["available"] is True and ov["reason"] is None
    assert ov["fetched_at"] == NOW.isoformat()
    assert [n["title"] for n in ov["notices"]] == ["상점 업데이트", NOTICES[0]["Title"]]
    assert ov["notices"][0]["date"] == "2026-11-19T10:00:00+09:00"
    assert [e["title"] for e in ov["events"]] == ["겨울 이벤트"]
    assert ov["events"][0]["end"] == "2026-12-10T06:00:00+09:00"
    assert [t["name"] for t in ov["today"]] == ["볼라르 섬", "메데이아", "세베크 아툰"]
    assert ov["maintenance"] is None  # 어제 끝난 점검
    assert ov["gold_island_subscribed"] is False


def test_snapshot_survives_restart(env, monkeypatch):
    _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.refresh_content(NOW))
    loa_content._reset_state_for_tests()  # 재시작 흉내 — 메모리 비움
    _install(monkeypatch, {})  # API가 아무것도 안 줘도
    ov = asyncio.run(loa_content.overview(ME, NOW))
    assert ov["available"] is True
    assert len(ov["today"]) == 3


def test_503_marks_outage_skips_rest_and_keeps_snapshot(env, monkeypatch):
    _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.refresh_content(NOW))
    session = _install(monkeypatch, {("GET", "/news/notices"): (503, "점검")})
    later = NOW + timedelta(minutes=31)
    assert asyncio.run(loa_content.refresh_content(later)) is False
    assert len(session.calls) == 1  # 첫 503에서 그 주기의 나머지 호출은 건너뛴다
    ov = asyncio.run(loa_content.overview(ME, later))
    assert ov["available"] is True  # 마지막 정상 스냅샷 유지
    assert ov["fetched_at"] == NOW.isoformat()
    assert ov["maintenance"]["active"] is True
    # 같은 주기 안에서는 다시 부르지 않는다
    asyncio.run(loa_content.tick(later + timedelta(minutes=1)))
    assert len(session.calls) == 1
    # 정상 응답이 오면 점검 표시가 풀린다
    _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.refresh_content(later + timedelta(minutes=31)))
    assert asyncio.run(loa_content.overview(ME, later + timedelta(minutes=31)))["maintenance"] is None


def test_503_without_snapshot_reports_unavailable_with_maintenance(env, monkeypatch):
    _install(monkeypatch, {("GET", "/news/notices"): (503, "점검")})
    asyncio.run(loa_content.refresh_content(NOW))
    ov = asyncio.run(loa_content.overview(ME, NOW))
    assert ov["available"] is False
    assert "점검" in ov["reason"]
    assert ov["maintenance"]["title"] == "점검 중"


def test_tick_respects_intervals(env, monkeypatch):
    session = _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.tick(NOW))
    first = len(session.calls)
    assert first >= 4  # 공지 2 + 이벤트 + 캘린더 (+ 시세는 추적 아이템이 없어 호출 없음)
    asyncio.run(loa_content.tick(NOW + timedelta(minutes=10)))
    assert len(session.calls) == first
    asyncio.run(loa_content.tick(NOW + timedelta(minutes=31)))
    assert len(session.calls) == first * 2


def test_no_server_key_reports_reason(env, monkeypatch):
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "")
    ov = asyncio.run(loa_content.overview(ME, NOW))
    assert ov["available"] is False and "설정되지 않았습니다" in ov["reason"]
    assert ov["notices"] == [] and ov["today"] == []
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "404")
    ov = asyncio.run(loa_content.overview(ME, NOW))
    assert ov["available"] is False and "찾을 수 없습니다" in ov["reason"]
    pr = asyncio.run(loa_content.prices())
    assert pr["available"] is False and pr["items"] == []


# ── 엔드포인트 ─────────────────────────────────────────────

def test_endpoints_overview_calendar_and_subscription(client, monkeypatch):
    _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.refresh_content(NOW))

    resp = client.post("/api/internal/loa/gold-island-subscription", json={"discord_id": ME, "enabled": True}, headers=HEADERS)
    assert resp.json() == {"success": True, "enabled": True}
    ov = client.get("/api/internal/loa/overview", params={"discord_id": ME}, headers=HEADERS).json()
    assert ov["gold_island_subscribed"] is True
    assert set(ov) >= {"available", "reason", "fetched_at", "maintenance", "notices", "events", "today", "gold_island_subscribed"}

    cal = client.get("/api/internal/loa/calendar", params={"date": "2026-11-20"}, headers=HEADERS).json()
    assert cal["available"] is True and cal["date"] == "2026-11-20"
    assert [i["name"] for i in cal["items"]] == ["메데이아"]
    item = cal["items"][0]
    assert set(item) == {"category", "name", "icon", "min_item_level", "times", "rewards", "is_gold"}

    bad = client.get("/api/internal/loa/calendar", params={"date": "어제"}, headers=HEADERS).json()
    assert bad["available"] is False and bad["items"] == []

    resp = client.post("/api/internal/loa/gold-island-subscription", json={"discord_id": ME, "enabled": False}, headers=HEADERS)
    assert resp.json() == {"success": True, "enabled": False}
    assert asyncio.run(db.is_gold_island_subscribed(ME)) is False


# ── 골드 섬 DM ─────────────────────────────────────────────

class _DMBot:
    pass


def test_gold_island_dm_once_per_day_and_survives_restart(env, monkeypatch):
    import bot.ui.views as views

    sent = []

    async def fake_send_dm(client, discord_id, content, *, kind="dm", message_id=None):
        sent.append((discord_id, kind, content))

    monkeypatch.setattr(views, "_send_dm", fake_send_dm)
    _install(monkeypatch, _content_routes())
    asyncio.run(loa_content.refresh_content(NOW))
    asyncio.run(db.set_gold_island_subscription(ME, True))
    asyncio.run(db.set_gold_island_subscription("556", True))

    # 11분 전 — 아직 아님
    assert asyncio.run(loa_content.gold_island_dm_tick(_DMBot(), datetime(2026, 11, 19, 20, 49, tzinfo=KST))) == 0
    # 10분 전 구간
    t = datetime(2026, 11, 19, 20, 52, tzinfo=KST)
    assert asyncio.run(loa_content.gold_island_dm_tick(_DMBot(), t)) == 2
    assert {s[0] for s in sent} == {ME, "556"}
    assert all(s[1] == "gold_island" for s in sent)
    assert "8분 뒤(21:00)" in sent[0][2] and "메데이아" in sent[0][2]

    # 재시작해도(메모리 초기화) 같은 날 다시 안 보낸다
    loa_content._reset_state_for_tests()
    assert asyncio.run(loa_content.gold_island_dm_tick(_DMBot(), t + timedelta(minutes=1))) == 0
    assert len(sent) == 2

    # 시작 뒤에는 늦게 보내지 않는다
    asyncio.run(db.set_gold_island_subscription("557", True))
    assert asyncio.run(loa_content.gold_island_dm_tick(_DMBot(), datetime(2026, 11, 19, 21, 1, tzinfo=KST))) == 0


# ── 거래소 ────────────────────────────────────────────────

def _market_routes(searches: dict):
    def search(_params, body):
        items = searches.get((body["CategoryCode"], body["ItemName"]), [])
        return (200, {"PageNo": 1, "PageSize": 10, "TotalCount": len(items), "Items": items})

    return {
        ("GET", "/markets/options"): (200, {"Categories": [{"Code": 50000, "CodeName": "강화 재료", "Subs": []},
                                                           {"Code": 60000, "CodeName": "배틀 아이템"}]}),
        ("POST", "/markets/items"): search,
        ("GET", "/markets/items/66102006"): (200, [{"Name": "운명의 파괴석", "Stats": [
            {"Date": "2026-11-19", "AvgPrice": 12.5, "TradeCount": 100},
            {"Date": "2026-11-18", "AvgPrice": 10.0, "TradeCount": 90},
        ]}]),
    }


DESTRUCTION = {"Id": 66102006, "Name": "운명의 파괴석", "Grade": "희귀", "Icon": "d.png",
               "YDayAvgPrice": 10.0, "RecentPrice": 12, "CurrentMinPrice": 12}


def test_tracked_items_admin_flow_and_prices(client, monkeypatch):
    session = _install(monkeypatch, _market_routes({
        (60000, "운명의 파괴석"): [DESTRUCTION],
        (50000, "운명의 파괴석"): [{**DESTRUCTION, "Name": "운명의 파괴석 주머니(소)", "Id": 1}],
    }))

    resp = client.post("/api/internal/admin/loa/tracked-items",
                       json={"discord_id": "222", "names": ["운명의 파괴석"]}, headers=HEADERS)
    assert resp.json()["success"] is False

    resp = client.post("/api/internal/admin/loa/tracked-items",
                       json={"discord_id": ADMIN_ID, "names": [" 운명의 파괴석 ", "없는 아이템", "운명의 파괴석"]},
                       headers=HEADERS)
    body = resp.json()
    assert body == {"success": True, "names": ["운명의 파괴석", "없는 아이템"], "unresolved": ["없는 아이템"]}
    ids = asyncio.run(db.get_market_item_ids())
    assert ids["운명의 파괴석"]["item_id"] == 66102006  # 정확히 같은 이름만
    assert ids["운명의 파괴석"]["category_code"] == 60000
    options_calls = [c for c in session.calls if c[1] == "/markets/options"]
    assert len(options_calls) == 1  # 카테고리 코드는 한 번만 받는다

    got = client.get("/api/internal/admin/loa/tracked-items", params={"discord_id": ADMIN_ID}, headers=HEADERS).json()
    assert got == {"names": ["운명의 파괴석", "없는 아이템"]}
    assert client.get("/api/internal/admin/loa/tracked-items", params={"discord_id": "222"}, headers=HEADERS).status_code == 403

    asyncio.run(loa_content.refresh_prices(NOW))
    pr = client.get("/api/internal/loa/prices", headers=HEADERS).json()
    assert pr["available"] is True and pr["fetched_at"] == NOW.isoformat()
    assert pr["items"] == [{
        "id": 66102006, "name": "운명의 파괴석", "icon": "d.png", "current": 12, "yday_avg": 10.0,
        "change_pct": 20.0,
        "history": [{"date": "2026-11-18", "avg": 10.0}, {"date": "2026-11-19", "avg": 12.5}],
    }]


def test_tracked_items_limit(client):
    names = [f"아이템{i}" for i in range(9)]
    resp = client.post("/api/internal/admin/loa/tracked-items", json={"discord_id": ADMIN_ID, "names": names}, headers=HEADERS)
    assert resp.json()["success"] is False


def test_prices_empty_when_no_tracked_items(client):
    pr = client.get("/api/internal/loa/prices", headers=HEADERS).json()
    assert pr["available"] is True and pr["items"] == []


def test_prices_503_keeps_previous(env, monkeypatch):
    asyncio.run(db.set_setting(loa_content.TRACKED_ITEMS_KEY, '["운명의 파괴석"]'))
    _install(monkeypatch, _market_routes({(50000, "운명의 파괴석"): [DESTRUCTION]}))
    asyncio.run(loa_content.refresh_prices(NOW))
    assert len(asyncio.run(loa_content.prices())["items"]) == 1
    session = _install(monkeypatch, {("POST", "/markets/items"): (503, "점검")})
    assert asyncio.run(loa_content.refresh_prices(NOW + timedelta(hours=1))) is False
    assert len(session.calls) == 1
    pr = asyncio.run(loa_content.prices())
    assert pr["fetched_at"] == NOW.isoformat() and len(pr["items"]) == 1
