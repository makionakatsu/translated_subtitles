from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from app.models import VideoMetadata


class MediaError(RuntimeError):
    pass


_RENDER_FFMPEG: Optional[str] = None


def is_supported_url(value: str) -> bool:
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _run(args: list, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def ffmpeg_has_filter(executable: str, filter_name: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return False
    return any(line.split()[1:2] == [filter_name] for line in result.stdout.splitlines() if line.strip())


def render_ffmpeg_executable() -> str:
    global _RENDER_FFMPEG
    if _RENDER_FFMPEG:
        return _RENDER_FFMPEG
    system = shutil.which("ffmpeg") or "ffmpeg"
    if ffmpeg_has_filter(system, "ass") or ffmpeg_has_filter(system, "subtitles"):
        _RENDER_FFMPEG = system
        return _RENDER_FFMPEG
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_has_filter(bundled, "ass") or ffmpeg_has_filter(bundled, "subtitles"):
            _RENDER_FFMPEG = bundled
            return _RENDER_FFMPEG
    except Exception:
        pass
    _RENDER_FFMPEG = system
    return _RENDER_FFMPEG


def parse_fps(value: str) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            den = float(denominator)
            return 0.0 if den == 0 else float(numerator) / den
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe_media(path: Path) -> VideoMetadata:
    if not path.exists() or not os.access(path, os.R_OK):
        raise MediaError(f"File is not readable: {path}")
    try:
        result = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"ffprobe failed: {exc}") from exc

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream and not audio_stream:
        raise MediaError("No audio or video streams found")
    duration = data.get("format", {}).get("duration") or (video_stream or {}).get("duration") or 0
    try:
        duration_ms = int(round(float(duration) * 1000))
    except (TypeError, ValueError):
        duration_ms = 0
    return VideoMetadata(
        width=int((video_stream or {}).get("width") or 0),
        height=int((video_stream or {}).get("height") or 0),
        duration_ms=duration_ms,
        fps=parse_fps((video_stream or {}).get("avg_frame_rate") or (video_stream or {}).get("r_frame_rate") or ""),
        has_audio=audio_stream is not None,
        has_video=video_stream is not None,
        format_name=data.get("format", {}).get("format_name") or "",
    )


def extract_audio(video_path: Path, audio_path: Path, cancel_check: Optional[Callable[[], None]] = None) -> Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    if cancel_check:
        cancel_check()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate()
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        raise
    if cancel_check:
        cancel_check()
    if proc.returncode != 0:
        raise MediaError((stderr or stdout or "ffmpeg audio extraction failed")[-4000:])
    return audio_path


def download_url(url: str, out_dir: Path) -> Path:
    if not is_supported_url(url):
        raise MediaError("URL must start with http:// or https://")
    try:
        import yt_dlp
    except ImportError as exc:
        raise MediaError("yt-dlp is not installed. Install it to import videos from URLs.") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "source.%(ext)s")
    options = {
        "outtmpl": output_template,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:
        raise MediaError(f"URL download failed: {exc}") from exc

    candidates = [
        path
        for path in out_dir.glob("source.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl", ".temp"))
    ]
    if not candidates:
        raise MediaError("URL download completed but no media file was produced")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def preflight_binary(name: str) -> tuple:
    path = shutil.which(name)
    return bool(path), path or f"{name} not found"
