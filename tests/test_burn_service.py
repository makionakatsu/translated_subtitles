"""Tests for ``burn_service``: focus on path-escaping and progress parsing.

The actual ffmpeg invocation is mocked via ``subprocess.run`` /
``subprocess.Popen`` so the tests run with no media stack.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apps.api.services import burn_service


def test_escape_subtitles_path_handles_quotes() -> None:
    p = Path("/tmp/subs with 'quote'.ass")
    escaped = burn_service._escape_subtitles_path(p)
    assert escaped == r"/tmp/subs with \'quote\'.ass"


def test_escape_subtitles_path_escapes_drive_colon() -> None:
    p = Path("C:/Users/test/subs.ass")
    escaped = burn_service._escape_subtitles_path(p)
    assert "\\:" in escaped


def test_burn_subtitles_invokes_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_run(cmd, check, capture_output):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    video = tmp_path / "movie.mp4"
    subs = tmp_path / "movie.ass"
    video.write_bytes(b"")
    subs.write_text("[Events]\n", encoding="utf-8")

    out = burn_service.burn_subtitles(video, subs, out_dir=tmp_path / "out", font_size=64)
    assert out.parent.exists()
    assert captured["cmd"][0] == "ffmpeg"
    assert any("force_style='Fontsize=64'" in a for a in captured["cmd"])
