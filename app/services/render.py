from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from app.models import CaptionProject, CaptionSegment, StylePreset
from app.services.quality import auto_font_size
from app.services.storage import artifact_path, save_project
from app.services.video import render_ffmpeg_executable


class RenderError(RuntimeError):
    pass


def format_srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def format_vtt_time(ms: int) -> str:
    return format_srt_time(ms).replace(",", ".")


def format_ass_time(ms: int) -> str:
    ms = max(0, int(ms))
    centiseconds = int(round(ms / 10.0))
    hours, rem = divmod(centiseconds, 360_000)
    minutes, rem = divmod(rem, 6_000)
    seconds, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02}:{seconds:02}.{cs:02}"


def ass_escape(text: str) -> str:
    return (text or "").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def srt_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def ffmpeg_filter_escape(path: Path) -> str:
    value = str(path)
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def segment_text(segment: CaptionSegment) -> str:
    return segment.display_text or segment.translated_text or segment.source_text or ""


def bilingual_segment_text(segment: CaptionSegment) -> str:
    source = (segment.source_text or "").strip()
    translated = (segment.translated_text or segment.display_text or "").strip()
    if source and translated and source != translated:
        return f"{source}\n{translated}"
    return segment_text(segment)


def write_srt(project: CaptionProject) -> Path:
    if not project.segments:
        raise RenderError("No caption segments. Run transcription before exporting subtitles.")
    path = artifact_path(project.id, "captions.srt")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for index, segment in enumerate(project.segments, 1):
        lines.append(str(index))
        lines.append(f"{format_srt_time(segment.start_ms)} --> {format_srt_time(segment.end_ms)}")
        lines.append(srt_text(segment_text(segment)))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    project.artifacts["srt_path"] = str(path)
    save_project(project)
    return path


def write_vtt(project: CaptionProject) -> Path:
    if not project.segments:
        raise RenderError("No caption segments. Run transcription before exporting subtitles.")
    path = artifact_path(project.id, "captions.vtt")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = ["WEBVTT", ""]
    for segment in project.segments:
        lines.append(f"{format_vtt_time(segment.start_ms)} --> {format_vtt_time(segment.end_ms)}")
        lines.append(srt_text(segment_text(segment)))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    project.artifacts["vtt_path"] = str(path)
    save_project(project)
    return path


def _style_line(project: CaptionProject, style: StylePreset) -> str:
    font_size = style.font_size if style.font_size_mode == "manual" else auto_font_size(project.metadata.width, project.metadata.height)
    margin_v = int(max(12, project.metadata.height * style.margin_v_ratio)) if project.metadata.height else 70
    margin_lr = int(max(16, project.metadata.width * 0.05)) if project.metadata.width else 60
    border_style = 3 if style.background_enabled else 1
    back_color = "&H80000000" if style.background_enabled else "&HFF000000"
    return (
        f"Style: Default,{style.font_family},{font_size},{style.primary_color},&H000000FF,"
        f"{style.outline_color},{back_color},0,0,0,0,100,100,0,0,{border_style},"
        f"{style.outline_px},{style.shadow_px},2,{margin_lr},{margin_lr},{margin_v},1"
    )


def write_ass(project: CaptionProject) -> Path:
    if not project.segments:
        raise RenderError("No caption segments. Run transcription before exporting subtitles.")
    path = artifact_path(project.id, "captions.ass")
    path.parent.mkdir(parents=True, exist_ok=True)
    width = project.metadata.width or 1920
    height = project.metadata.height or 1080
    style = project.style
    lines = [
        "[Script Info]",
        "Title: Local Caption MVP",
        "ScriptType: v4.00+",
        "Collisions: Normal",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line(project, style),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for segment in project.segments:
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start_ms)},{format_ass_time(segment.end_ms)},Default,,0,0,0,,{ass_escape(segment_text(segment))}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    project.artifacts["ass_path"] = str(path)
    save_project(project)
    return path


def write_bilingual_ass(project: CaptionProject) -> Path:
    if not project.segments:
        raise RenderError("No caption segments. Run transcription before exporting subtitles.")
    path = artifact_path(project.id, "captions_bilingual.ass")
    path.parent.mkdir(parents=True, exist_ok=True)
    width = project.metadata.width or 1920
    height = project.metadata.height or 1080
    style = project.style
    lines = [
        "[Script Info]",
        "Title: Local Caption MVP Bilingual",
        "ScriptType: v4.00+",
        "Collisions: Normal",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line(project, style),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for segment in project.segments:
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start_ms)},{format_ass_time(segment.end_ms)},Default,,0,0,0,,{ass_escape(bilingual_segment_text(segment))}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    project.artifacts["bilingual_ass_path"] = str(path)
    save_project(project)
    return path


def _run_ffmpeg(cmd: List[str], cancel_check: Optional[Callable[[], None]] = None) -> None:
    if cancel_check:
        cancel_check()
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
        raise RenderError((stderr or stdout or "ffmpeg failed")[-4000:])


def _burn_mp4_to_path(
    project: CaptionProject,
    output_path: Path,
    cancel_check: Optional[Callable[[], None]] = None,
    duration_sec: Optional[int] = None,
) -> Path:
    ass_path = write_ass(project)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.mp4")
    video_path = Path(project.video_path)
    vf = f"ass={ffmpeg_filter_escape(ass_path)}"
    ffmpeg_exe = render_ffmpeg_executable()
    primary = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(video_path),
    ]
    if duration_sec:
        primary.extend(["-t", str(duration_sec)])
    primary.extend(["-vf", vf, "-c:v", "h264_videotoolbox", "-b:v", "6000k", "-c:a", "copy", str(tmp_path)])
    fallback = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(video_path),
    ]
    if duration_sec:
        fallback.extend(["-t", str(duration_sec)])
    fallback.extend(["-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(tmp_path)])
    try:
        _run_ffmpeg(primary, cancel_check)
    except RenderError:
        if tmp_path.exists():
            tmp_path.unlink()
        _run_ffmpeg(fallback, cancel_check)
    os.replace(tmp_path, output_path)
    return output_path


def burn_mp4(project: CaptionProject, cancel_check: Optional[Callable[[], None]] = None) -> Path:
    output_path = artifact_path(project.id, "output_burned.mp4")
    _burn_mp4_to_path(project, output_path, cancel_check)
    project.artifacts["burned_mp4_path"] = str(output_path)
    save_project(project)
    return output_path


def burn_preview_mp4(project: CaptionProject, cancel_check: Optional[Callable[[], None]] = None, duration_sec: int = 15) -> Path:
    output_path = artifact_path(project.id, "preview_burned.mp4")
    _burn_mp4_to_path(project, output_path, cancel_check, duration_sec=duration_sec)
    project.artifacts["preview_mp4_path"] = str(output_path)
    save_project(project)
    return output_path
