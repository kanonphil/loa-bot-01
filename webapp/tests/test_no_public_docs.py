import pytest


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_not_exposed(client, path):
    """로그인 없이 전체 라우트 목록이 공개되면 안 된다."""
    assert client.get(path, follow_redirects=False).status_code == 404
