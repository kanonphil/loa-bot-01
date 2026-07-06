"""webapp.sanitize.clean_html 검증 — 게시판 에디터가 만들어낸 HTML 정제 규칙."""
from webapp.sanitize import clean_html


def test_strips_script_tags():
    assert "<script>" not in clean_html("<p>hi</p><script>alert(1)</script>")


def test_strips_event_handler_attributes():
    result = clean_html('<img src="/x.png" onerror="alert(1)">')
    assert "onerror" not in result


def test_strips_javascript_protocol_from_links():
    result = clean_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in result


def test_preserves_link_target_and_rel():
    """새 창 링크(target=_blank, rel=noopener)는 에디터가 명시적으로 붙이는 안전한 속성이라 유지돼야 한다."""
    result = clean_html('<a href="https://example.com" target="_blank" rel="noopener noreferrer">link</a>')
    assert 'href="https://example.com"' in result
    assert 'target="_blank"' in result
    assert 'rel="noopener noreferrer"' in result


def test_preserves_allowed_image_and_paragraph_markup():
    html = '<p>안녕</p><img src="/static/uploads/board/x.png" alt="사진">'
    assert clean_html(html) == html
