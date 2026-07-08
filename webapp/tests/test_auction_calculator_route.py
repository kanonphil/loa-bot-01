"""경매 분배금 계산기 페이지 검증 — 순수 계산 페이지라 로그인 게이트만 확인."""
import respx

from webapp.tests.conftest import log_in


def test_requires_login(client):
    resp = client.get("/tools/auction-calculator")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_renders_calculator_form(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/tools/auction-calculator")

    assert resp.status_code == 200
    assert 'id="calc-price"' in resp.text
    assert 'name="calc-party-size"' in resp.text
    assert 'id="calc-party-size-custom"' in resp.text
    assert 'id="calc-use-bid"' in resp.text
    assert 'id="calc-sell-breakeven"' in resp.text
