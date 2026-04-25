"""Phase 0 snapshot tests.

These freeze the *current* output of the existing subtitle writers so the
upcoming refactor (Streamlit removal, mlx-whisper migration, Gemini-only
translation) cannot silently change the bytes that downstream tools depend on.

Two output paths are pinned:

1. ``utils.processing._write_srt`` / ``_write_ass`` — the inline writers used
   today by ``processing.process_video``. These are scheduled for removal in
   later phases; pinning them now makes the diff explicit.
2. ``utils.srt_utils.generate_srt_content`` and
   ``utils.ass_utils.generate_ass_header`` — the alternative writers we plan to
   keep and reuse from ``apps/api/services/subtitle_service.py``.

We use plain string equality against checked-in ``.snap`` files so pytest can
run without the ``syrupy`` dependency on minimal CI images. Update snapshots by
running ``pytest --update-snapshots``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utils.ass_utils import generate_ass_header
from utils.processing import _write_ass, _write_srt
from utils.srt_utils import format_srt_time, generate_srt_content
from utils.style_loader import load_styles

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _read_or_write(path: Path, value: str, update: bool) -> str:
    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value
    return path.read_text(encoding="utf-8")


def pytest_addoption_compat(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-snapshots", default=False))


@pytest.fixture
def update_snapshots(request: pytest.FixtureRequest) -> bool:
    try:
        return bool(request.config.getoption("--update-snapshots"))
    except ValueError:
        return False


def test_format_srt_time_round_trips() -> None:
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_srt_time(3599.5) == "00:59:59,500"
    assert format_srt_time(3600.001) == "01:00:00,001"


def test_processing_write_srt_snapshot(
    sample_segments, tmp_path: Path, update_snapshots: bool
) -> None:
    out = tmp_path / "out.srt"
    _write_srt(sample_segments, out)
    actual = out.read_text(encoding="utf-8")
    expected = _read_or_write(SNAPSHOT_DIR / "processing_write_srt.snap", actual, update_snapshots)
    assert actual == expected


def test_processing_write_ass_snapshot(
    sample_segments, tmp_path: Path, update_snapshots: bool
) -> None:
    out = tmp_path / "out.ass"
    _write_ass(sample_segments, out, font_size=48)
    actual = out.read_text(encoding="utf-8")
    expected = _read_or_write(SNAPSHOT_DIR / "processing_write_ass.snap", actual, update_snapshots)
    assert actual == expected


def test_srt_utils_generate_srt_content_snapshot(
    sample_segments, update_snapshots: bool
) -> None:
    actual = generate_srt_content(sample_segments, width=1920, font_size=48)
    expected = _read_or_write(
        SNAPSHOT_DIR / "srt_utils_generate.snap", actual, update_snapshots
    )
    assert actual == expected


def test_ass_utils_header_snapshot(update_snapshots: bool) -> None:
    styles = load_styles()
    actual = generate_ass_header(
        width=1920,
        height=1080,
        styles_data=styles,
        chosen_style_name="Yu Gothic UI",
        font_size=48,
    )
    expected = _read_or_write(
        SNAPSHOT_DIR / "ass_utils_header.snap", actual, update_snapshots
    )
    assert actual == expected
