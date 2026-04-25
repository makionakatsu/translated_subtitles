from __future__ import annotations

from apps.api.services import style_service


def test_load_styles_returns_bundled_styles() -> None:
    style_service.reset_cache()
    styles = style_service.load_styles()
    assert "Yu Gothic UI" in styles
    assert styles["Yu Gothic UI"]["Fontname"] == "Yu Gothic UI"


def test_load_styles_caches_after_first_call() -> None:
    style_service.reset_cache()
    a = style_service.load_styles()
    b = style_service.load_styles()
    assert a == b
