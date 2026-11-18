"""Conversion timeouts must not destroy prior outputs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from apps.api.services import media_service


def test_timeout_preserves_existing_output_and_removes_partial(monkeypatch, tmp_path):
    output = tmp_path / "existing.wav"
    output.write_bytes(b"previous result")
    monkeypatch.setattr(media_service.shutil, "which", lambda _: "/fake/ffmpeg")

    def timed_out(cmd, **kwargs):
        Path(cmd[-2]).write_bytes(b"partial result")
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(media_service.subprocess, "run", timed_out)
    with pytest.raises(media_service.MediaError, match="timed out"):
        media_service.convert_to_wav(tmp_path / "source.mp4", output)
    assert output.read_bytes() == b"previous result"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing.wav"]


def test_success_replaces_output_only_after_conversion(monkeypatch, tmp_path):
    output = tmp_path / "existing.wav"
    output.write_bytes(b"previous result")
    monkeypatch.setattr(media_service.shutil, "which", lambda _: "/fake/ffmpeg")

    def succeeds(cmd, **kwargs):
        assert output.read_bytes() == b"previous result"
        Path(cmd[-2]).write_bytes(b"new result")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(media_service.subprocess, "run", succeeds)
    assert media_service.convert_to_wav(tmp_path / "source.mp4", output) == output
    assert output.read_bytes() == b"new result"


def test_same_input_and_output_is_rejected_without_damage(monkeypatch, tmp_path):
    monkeypatch.setattr(media_service.shutil, "which", lambda _: "/fake/ffmpeg")
    path = tmp_path / "source.wav"
    path.write_bytes(b"original")
    with pytest.raises(media_service.MediaError, match="different files"):
        media_service.convert_to_wav(path, path)
    assert path.read_bytes() == b"original"


def test_real_hung_child_is_stopped_and_existing_output_is_preserved(monkeypatch, tmp_path):
    executable = tmp_path / "ffmpeg"
    pidfile = tmp_path / "child.pid"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
        "pathlib.Path(sys.argv[-2]).write_bytes(b'partial')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(media_service, "_CONVERT_TIMEOUT_SECONDS", 0.5)
    output = tmp_path / "existing.wav"
    output.write_bytes(b"previous result")
    with pytest.raises(media_service.MediaError, match="timed out"):
        media_service.convert_to_wav(tmp_path / "source.mp4", output)
    assert output.read_bytes() == b"previous result"
    assert not list(tmp_path.glob(".audio-convert-*"))
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
