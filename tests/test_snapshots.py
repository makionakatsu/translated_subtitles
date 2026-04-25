"""Snapshot tests for the canonical subtitle writers.

Pin the byte-for-byte output of :mod:`apps.api.services.subtitle_service` so
the upcoming editor and translation work cannot silently regress the file
formats downstream tools (Final Cut Pro, ffmpeg, browser players) consume.

Update with ``pytest --update-snapshots``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.services import style_service
from apps.api.services.subtitle_service import (
    format_srt_time,
    render_ass_header,
    write_ass,
    write_fcpxml,
    write_srt,
)

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _read_or_write(path: Path, value: str, update: bool) -> str:
    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value
    return path.read_text(encoding="utf-8")


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


def test_write_srt_snapshot(sample_segments, tmp_path: Path, update_snapshots: bool) -> None:
    out = tmp_path / "out.srt"
    write_srt(sample_segments, out)
    actual = out.read_text(encoding="utf-8")
    expected = _read_or_write(SNAPSHOT_DIR / "subtitle_service_srt.snap", actual, update_snapshots)
    assert actual == expected


def test_write_ass_snapshot(sample_segments, tmp_path: Path, update_snapshots: bool) -> None:
    styles = style_service.load_styles()
    out = tmp_path / "out.ass"
    write_ass(
        sample_segments,
        out,
        width=1920,
        height=1080,
        styles_data=styles,
        style_name="Yu Gothic UI",
        font_size=48,
    )
    actual = out.read_text(encoding="utf-8")
    expected = _read_or_write(SNAPSHOT_DIR / "subtitle_service_ass.snap", actual, update_snapshots)
    assert actual == expected


def test_render_ass_header_snapshot(update_snapshots: bool) -> None:
    styles = style_service.load_styles()
    actual = render_ass_header(
        width=1920,
        height=1080,
        styles_data=styles,
        style_name="Yu Gothic UI",
        font_size=48,
    )
    expected = _read_or_write(
        SNAPSHOT_DIR / "subtitle_service_ass_header.snap", actual, update_snapshots
    )
    assert actual == expected


def test_write_fcpxml_snapshot(sample_segments, tmp_path: Path, update_snapshots: bool) -> None:
    out = tmp_path / "out.fcpxml"
    write_fcpxml(
        sample_segments,
        out,
        width=1920,
        height=1080,
        frame_rate=24.0,
        duration_sec=4000.0,
        font_size=48,
    )
    actual = out.read_text(encoding="utf-8")
    # FCPXML embeds a generation timestamp; strip the comment for snapshotting.
    import re

    actual_normalised = re.sub(r"<!-- Generated.*? -->", "<!-- Generated -->", actual)
    expected = _read_or_write(
        SNAPSHOT_DIR / "subtitle_service_fcpxml.snap", actual_normalised, update_snapshots
    )
    assert actual_normalised == expected
