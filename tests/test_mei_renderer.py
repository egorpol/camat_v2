from __future__ import annotations

import pytest

from camat.mei_renderer import (
    DEFAULT_MEI,
    make_mei_renderer_html,
    validate_mei_text,
)


def test_validate_mei_text_accepts_complete_document() -> None:
    validate_mei_text(DEFAULT_MEI)


def test_validate_mei_text_rejects_non_mei_root() -> None:
    with pytest.raises(ValueError, match="document root must be <mei>"):
        validate_mei_text("<score/>")


def test_renderer_html_uses_requested_zoom_width() -> None:
    html = make_mei_renderer_html(
        "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        viewer_id="test-renderer",
        zoom_percent=200,
        viewer_max_height=960,
    )

    assert 'id="test-renderer"' in html
    assert "width: 200%;" in html
    assert "max-height: 960px;" in html
    assert "<script" not in html
