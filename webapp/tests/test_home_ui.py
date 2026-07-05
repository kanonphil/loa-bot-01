"""홈(빈 상태)/사이드바/랜덤 환영 문구가 실제로 렌더되는지 검증."""
import respx

from webapp.content.greetings import _TEMPLATES, random_welcome
from webapp.tests.conftest import log_in


def test_random_welcome_returns_known_phrase():
    msg = random_welcome("테스터")
    assert any(msg == t.format(username="테스터") for t in _TEMPLATES)


def test_random_welcome_uses_all_templates_over_many_draws():
    seen = {random_welcome("테스터") for _ in range(200)}
    # 200번 뽑았는데 후보가 6개면 전부 최소 한 번은 나오는 게 정상 (확률적으로 거의 확실)
    assert len(seen) == len(_TEMPLATES)


def test_home_renders_sidebar_logo_and_empty_state(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/home")
    assert resp.status_code == 200
    body = resp.text
    # 사이드바 / 로고 / 네비게이션 / 최근 세션 섹션
    assert 'class="sidebar"' in body
    assert "logo.svg" in body
    assert "새 채팅" in body
    assert "레이드 체크" in body
    assert "최근" in body
    # 빈 상태(참고 화면과 동일한 가운데 정렬 인사말 + 입력 폼)
    assert 'class="empty-state"' in body
    assert 'hx-post="/chat/send"' in body
    # AI 상담이 아직 상세 작업은 못한다는 공지
    assert 'class="ai-notice"' in body
    assert "상세한 분석이나 작업 수행은 아직 지원하지 않습니다" in body
