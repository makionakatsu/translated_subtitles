"""Subtitle file writers: SRT, ASS, FCPXML.

Replaces the legacy ``utils/srt_utils.py``, ``utils/ass_utils.py`` and
``utils/fcpxml_utils.py`` and the inline ``_write_srt`` / ``_write_ass`` in
``utils/processing.py``. The ASS writer respects ``styles.json`` (the legacy
inline writer hard-coded a Meiryo style and ignored ``styles.json`` entirely).

All writers accept any iterable of objects exposing ``start``, ``end`` and
``text`` — duck typing matches both backend :class:`Segment` instances and the
plain dataclasses used in tests.
"""
from __future__ import annotations

import datetime as _dt
import io
import logging
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class _HasTiming(Protocol):
    start: float
    end: float
    text: str


# ─────────────────────────────────────────────────────────────────────────────
# Time formatting
# ─────────────────────────────────────────────────────────────────────────────


def format_srt_time(seconds: float | None) -> str:
    """``hh:mm:ss,mmm`` SRT timestamp."""
    if seconds is None:
        return "00:00:00,000"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    ms = round((s - int(s)) * 1000)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{ms:03}"


def format_ass_time(seconds: float | None) -> str:
    """``h:mm:ss.cc`` ASS timestamp (centiseconds)."""
    if seconds is None:
        return "0:00:00.00"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    cs = round((s - int(s)) * 100)
    return f"{int(h)}:{int(m):02}:{int(s):02}.{cs:02}"


def srt_time_to_seconds(srt_time: str) -> float:
    """Inverse of :func:`format_srt_time`."""
    try:
        h, m, s_ms = srt_time.split(":")
        s, ms = s_ms.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except ValueError:
        logger.warning("Could not parse SRT time format: %s", srt_time)
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Segment access helpers (duck typing)
# ─────────────────────────────────────────────────────────────────────────────


def _attr(seg: Any, name: str, default: Any = None) -> Any:
    if hasattr(seg, name):
        return getattr(seg, name)
    if isinstance(seg, dict):
        return seg.get(name, default)
    return default


def _normalise_text(raw: Any) -> str:
    """Strip and replace embedded newlines with spaces (single-line write)."""
    text = (raw or "").strip().replace("\r\n", "\n").replace("\n", " ")
    # Collapse internal whitespace runs that the newline replacement may create.
    return " ".join(text.split())


# ─────────────────────────────────────────────────────────────────────────────
# SRT
# ─────────────────────────────────────────────────────────────────────────────


def write_srt(segments: Iterable[Any], out_path: Path) -> Path:
    """Write a minimal, faithful SRT file.

    No regex stripping is applied; emoji, CJK punctuation, and non-ASCII glyphs
    are preserved verbatim. Wrapping is intentionally *not* performed here;
    that is a presentation concern handled by the editor (CPS-aware splitter).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start = format_srt_time(_attr(seg, "start"))
            end = format_srt_time(_attr(seg, "end"))
            text = _normalise_text(_attr(seg, "text", ""))
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# ASS
# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_STYLE: dict[str, str] = {
    "Fontname": "Arial",
    "PrimaryColour": "&H00FFFFFF",
    "SecondaryColour": "&H000000FF",
    "OutlineColour": "&H00000000",
    "BackColour": "&H64000000",
    "Bold": "0",
    "Italic": "0",
    "Underline": "0",
    "StrikeOut": "0",
    "ScaleX": "100",
    "ScaleY": "100",
    "Spacing": "0",
    "Angle": "0",
    "BorderStyle": "1",
    "Outline": "2",
    "Shadow": "0",
    "Alignment": "2",
    "MarginL": "15",
    "MarginR": "15",
    "MarginV": "10",
    "Encoding": "1",
}


def _ass_text(raw: Any) -> str:
    """ASS uses ``\\N`` for hard line breaks. Trim then convert literal newlines."""
    return (raw or "").strip().replace("\r\n", "\n").replace("\n", "\\N")


def render_ass_header(
    *,
    width: int,
    height: int,
    styles_data: dict[str, dict[str, str]],
    style_name: str = "Default",
    font_size: int = 48,
    show_bg: bool = False,
) -> str:
    chosen = styles_data.get(style_name)
    if chosen is None:
        # Fall back to the first defined style, or to the inline default.
        chosen = next(iter(styles_data.values()), {}) if styles_data else {}
    # styles.json may use int values for numeric fields; coerce to string.
    style = {**_DEFAULT_STYLE, **{k: str(v) for k, v in chosen.items()}}

    if show_bg:
        back = style.get("BackColour", "&H80000000")
        rgb = back[4:] if len(back) == 10 and back.startswith("&H") else "000000"
        style["BackColour"] = f"&H00{rgb}"
        style["BorderStyle"] = "3"
    else:
        style["BackColour"] = "&HFF000000"

    style["MarginV"] = str(int(height * 0.05))
    style["MarginL"] = style["MarginR"] = str(int(width * 0.05))

    style_line = ",".join(
        [
            style_name,
            style["Fontname"],
            str(max(10, int(font_size))),
            style["PrimaryColour"],
            style["SecondaryColour"],
            style["OutlineColour"],
            style["BackColour"],
            style["Bold"],
            style["Italic"],
            style["Underline"],
            style["StrikeOut"],
            style["ScaleX"],
            style["ScaleY"],
            style["Spacing"],
            style["Angle"],
            style["BorderStyle"],
            style["Outline"],
            style["Shadow"],
            style["Alignment"],
            style["MarginL"],
            style["MarginR"],
            style["MarginV"],
            style["Encoding"],
        ]
    )

    return (
        "[Script Info]\n"
        "Title: Generated by translated_subtitles\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 1\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: None\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {style_line}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def write_ass(
    segments: Iterable[Any],
    out_path: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    styles_data: dict[str, dict[str, str]] | None = None,
    style_name: str = "Default",
    font_size: int = 48,
    show_bg: bool = False,
) -> Path:
    """Write a complete ASS file using the chosen style from ``styles.json``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = render_ass_header(
        width=width,
        height=height,
        styles_data=styles_data or {},
        style_name=style_name,
        font_size=font_size,
        show_bg=show_bg,
    )
    with out_path.open("w", encoding="utf-8") as f:
        f.write(header)
        for seg in segments:
            start = format_ass_time(_attr(seg, "start"))
            end = format_ass_time(_attr(seg, "end"))
            text = _ass_text(_attr(seg, "text", ""))
            f.write(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}\n")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# FCPXML
# ─────────────────────────────────────────────────────────────────────────────


def _to_fractional_time(seconds: float | None, frame_rate: float = 24.0) -> str:
    if seconds is None:
        return "0/1s"
    rate = float(frame_rate) if frame_rate > 0 else 24.0
    total_frames = max(0, round(seconds * rate))
    if rate.is_integer():
        return f"{total_frames}/{int(rate)}s"
    return f"{total_frames}/{rate:.2f}s"


def write_fcpxml(
    segments: Iterable[Any],
    out_path: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    frame_rate: float = 24.0,
    duration_sec: float | None = None,
    font: str = "Helvetica",
    font_size: int = 48,
) -> Path:
    """Write a Final Cut Pro X-friendly FCPXML."""
    segs = list(segments)
    if not segs:
        out_path.write_text(
            '<?xml version="1.0"?><fcpxml version="1.13"></fcpxml>',
            encoding="utf-8",
        )
        return out_path

    last_end = max(_attr(s, "end", 0.0) or 0.0 for s in segs)
    if duration_sec is None:
        duration_sec = math.ceil(last_end) + 1
    duration_sec = max(duration_sec, math.ceil(last_end) + 1)
    margin_v = int(height * 0.05)

    fcpxml = ET.Element("fcpxml", version="1.13")
    fcpxml.append(
        ET.Comment(f" Generated by translated_subtitles on {_dt.datetime.now().isoformat()} ")
    )
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"FFVideoFormat{height}p{frame_rate:.2f}",
        frameDuration=f"{int(100000 / frame_rate)}/100000s" if frame_rate else "100/2400s",
        width=str(width),
        height=str(height),
    )
    ET.SubElement(
        resources,
        "effect",
        id="r2",
        name="Basic Title",
        uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti",
    )

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="Subtitle Import")
    project = ET.SubElement(event, "project", name="Generated Subtitles Project")
    sequence = ET.SubElement(
        project,
        "sequence",
        duration=_to_fractional_time(duration_sec, frame_rate),
        format="r1",
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")
    gap = ET.SubElement(
        spine,
        "gap",
        name="Base Gap",
        offset="0s",
        duration=_to_fractional_time(duration_sec, frame_rate),
        start="0s",
    )

    for i, seg in enumerate(segs, start=1):
        start_s = float(_attr(seg, "start", 0.0))
        end_s = float(_attr(seg, "end", start_s))
        text = (_attr(seg, "text", "") or "").strip()
        if start_s >= end_s or not text:
            continue
        title = ET.SubElement(
            gap,
            "title",
            name=text[:30],
            lane="1",
            offset=_to_fractional_time(start_s, frame_rate),
            ref="r2",
            duration=_to_fractional_time(max(end_s - start_s, 1 / frame_rate), frame_rate),
        )
        text_elem = ET.SubElement(title, "text")
        ts_ref = f"ts{i}"
        text_style = ET.SubElement(text_elem, "text-style", ref=ts_ref)
        text_style.text = text
        ET.SubElement(title, "text-style-def", id=ts_ref)
        ET.SubElement(
            title,
            "param",
            name="Position",
            key="9999/999166631/999166633/1/100/101",
            value=f"0 -{margin_v}",
        )
        ET.SubElement(
            title,
            "param",
            name="Alignment",
            key="9999/999166631/999166633/1/100/100",
            value="1",
        )
        ET.SubElement(
            title,
            "param",
            name="Font",
            key="9999/999166631/999166633/5/100/105",
            value=font,
        )
        ET.SubElement(
            title,
            "param",
            name="Size",
            key="9999/999166631/999166633/5/100/103",
            value=str(max(10, int(font_size))),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    ET.ElementTree(fcpxml).write(buf, encoding="unicode", xml_declaration=True)
    out_path.write_text(buf.getvalue(), encoding="utf-8")
    return out_path
