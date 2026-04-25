"""ffmpeg subtitle burn-in.

Replaces ``utils/burn_utils.py``. Two safety improvements over the legacy:

1. Subtitle paths are escaped using ffmpeg's ``subtitles`` filter rules
   (``\\`` and ``'`` escaping) so spaces and apostrophes in user-chosen paths
   do not break the filtergraph.
2. ``-progress pipe:1`` output is parsed line-by-line so callers receive
   real percentages instead of an opaque spinner.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class BurnError(RuntimeError):
    """Raised when ffmpeg burn-in fails."""


def _escape_subtitles_path(path: Path) -> str:
    """Escape a path for the ``subtitles`` filter.

    The filter argument lives inside a quoted filter expression. ``\\`` becomes
    ``\\\\`` and ``'`` becomes ``\\'`` per ffmpeg's documentation:
    https://ffmpeg.org/ffmpeg-filters.html#subtitles-1
    """
    return str(path).replace("\\", "\\\\").replace("'", r"\'").replace(":", r"\:")


def burn_subtitles(
    video_path: Path,
    subtitle_path: Path,
    *,
    out_dir: Path,
    font_size: int = 48,
    force_style_extra: dict[str, str] | None = None,
    on_progress: ProgressCallback | None = None,
    duration_sec: float | None = None,
) -> Path:
    """Burn ``subtitle_path`` into ``video_path``; returns the output mp4."""
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"burn_{video_path.stem}.mp4"

    style_pairs = {"Fontsize": str(font_size), **(force_style_extra or {})}
    style_str = ",".join(f"{k}={v}" for k, v in style_pairs.items())

    sub_arg = f"subtitles='{_escape_subtitles_path(subtitle_path)}':force_style='{style_str}'"

    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-vf",
        sub_arg,
        "-c:a",
        "copy",
        "-y",
    ]
    if on_progress is not None:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd.append(str(output_path))

    if on_progress is None:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
            raise BurnError(stderr) from e
        return output_path

    # Streaming progress mode: parse `out_time_us` and `progress` keys.
    total_us = int((duration_sec or 0.0) * 1_000_000)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and total_us:
                try:
                    pct = min(100.0, max(0.0, int(value) / total_us * 100.0))
                except ValueError:
                    continue
                on_progress(pct, f"Burning… {pct:.1f}%")
            elif key == "progress" and value == "end":
                on_progress(100.0, "Burn complete")
        rc = proc.wait()
    finally:
        if proc.stderr:
            proc.stderr.close()
    if rc != 0:
        raise BurnError(f"ffmpeg returned {rc}")
    return output_path
