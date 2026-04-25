"""Media I/O: yt-dlp downloads, ffmpeg WAV conversion and probing.

Replaces ``utils/video_utils.py`` and ``utils/processing.download_video``.
Streamlit progress hooks are removed; callers pass a plain
``Callable[[float, str], None]`` instead, which the FastAPI worker forwards to
SSE/WebSocket subscribers.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class MediaError(RuntimeError):
    """Raised when a media operation fails irrecoverably."""


def is_valid_url(value: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_video_resolution(input_path: str | Path) -> tuple[int, int]:
    """Return ``(width, height)`` or ``(0, 0)`` on failure."""
    try:
        import ffmpeg  # type: ignore[import-not-found]

        info = ffmpeg.probe(str(input_path))
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                return int(stream.get("width", 0) or 0), int(stream.get("height", 0) or 0)
    except Exception as e:
        logger.error("Failed to probe %s: %s", input_path, e)
    return 0, 0


def get_video_metadata(input_path: str | Path) -> dict[str, float | int | str]:
    """Return a coarse media metadata dict; missing fields default to ``0``/``""``."""
    try:
        import ffmpeg  # type: ignore[import-not-found]

        info = ffmpeg.probe(str(input_path))
    except Exception as e:
        logger.error("ffmpeg.probe failed for %s: %s", input_path, e)
        return {"width": 0, "height": 0, "duration": 0.0, "frame_rate": 0.0}

    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    width = int((video_stream or {}).get("width", 0) or 0)
    height = int((video_stream or {}).get("height", 0) or 0)

    fr_str = (video_stream or {}).get("r_frame_rate") or (video_stream or {}).get("avg_frame_rate")
    frame_rate = 0.0
    if isinstance(fr_str, str) and "/" in fr_str:
        try:
            num, den = fr_str.split("/")
            num_f, den_f = float(num), float(den)
            if den_f:
                frame_rate = num_f / den_f
        except ValueError:
            frame_rate = 0.0

    duration_str = (video_stream or {}).get("duration") or info.get("format", {}).get("duration")
    try:
        duration = float(duration_str) if duration_str else 0.0
    except (TypeError, ValueError):
        duration = 0.0

    return {"width": width, "height": height, "duration": duration, "frame_rate": frame_rate}


def convert_to_wav(input_path: str | Path, output_path: str | Path) -> Path:
    """Convert any media to 16 kHz mono PCM WAV (Whisper's expected format)."""
    if shutil.which("ffmpeg") is None:
        raise MediaError("ffmpeg not found on PATH")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
        "-y",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
        raise MediaError(f"ffmpeg failed converting to wav: {stderr}") from e
    return output_path


def download_video(
    url: str,
    output_dir: Path,
    *,
    prefix: str = "",
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download a video via yt-dlp. Returns the saved file path."""
    import yt_dlp  # type: ignore[import-not-found]

    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(output_dir / f"{prefix}%(id)s.%(ext)s")

    ydl_opts: dict[str, object] = {
        "outtmpl": out_template,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "postprocessors": [
            {"key": "FFmpegMerger"},
            {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
        ],
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [],
    }

    if on_progress is not None:

        def _hook(d: dict[str, object]) -> None:
            status = d.get("status")
            if status == "downloading":
                pct_str = (d.get("_percent_str") or "").strip().rstrip("%") if isinstance(d.get("_percent_str"), str) else ""
                try:
                    pct = float(pct_str)
                except ValueError:
                    pct = 0.0
                speed = d.get("_speed_str", "")
                eta = d.get("_eta_str", "")
                on_progress(pct, f"Downloading… {pct:.1f}% ({speed} ETA {eta})")
            elif status == "finished":
                on_progress(100.0, "Download complete")

        ydl_opts["progress_hooks"] = [_hook]

    info_dict: dict[str, object] | None = None

    def _run(opts: dict[str, object]) -> dict[str, object]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)

    try:
        info_dict = _run(ydl_opts)
    except yt_dlp.utils.DownloadError as e:
        if "Requested format is not available" in str(e):
            logger.warning("Falling back to generic 'best' format for %s", url)
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            info_dict = _run(ydl_opts)
        else:
            raise MediaError(str(e)) from e
    except KeyError as e:
        logger.warning("yt-dlp KeyError merging streams (%s); retrying with simple 'best'", e)
        info_dict = _run({"outtmpl": out_template, "format": "best", "quiet": True})

    if not info_dict:
        raise MediaError("yt-dlp returned no info dict")

    requested = info_dict.get("requested_downloads") or [info_dict]
    candidate = requested[0] if isinstance(requested, list) and requested else info_dict
    filepath = candidate.get("filepath") or candidate.get("_filename")
    if not filepath:
        raise MediaError("yt-dlp did not report a filepath after download")
    return Path(str(filepath))
