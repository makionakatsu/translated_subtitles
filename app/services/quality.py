from __future__ import annotations

from typing import List

from app.models import CaptionProject, CaptionSegment


JA_LINE_LIMIT = 22
EN_LINE_LIMIT = 42
MIN_DURATION_MS = 1000
MAX_DURATION_MS = 6000
MIN_GAP_MS = 40


def is_japanese_text(text: str) -> bool:
    return any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in text)


def reading_cps(text: str, duration_ms: int) -> float:
    if duration_ms <= 0:
        return 999.0
    visible = text.replace("\n", "")
    return len(visible) / (duration_ms / 1000.0)


def apply_quality(project: CaptionProject) -> CaptionProject:
    previous: CaptionSegment = None  # type: ignore[assignment]
    for segment in project.segments:
        warnings: List[str] = []
        if not segment.locked:
            segment.display_text = (segment.display_text or "").strip()
        text = segment.display_text or segment.translated_text or segment.source_text or ""
        duration_ms = segment.end_ms - segment.start_ms
        if not text.strip():
            warnings.append("EMPTY_TEXT")
        if segment.start_ms >= segment.end_ms:
            warnings.append("INVALID_TIME")
        if previous and segment.start_ms < previous.end_ms:
            warnings.append("OVERLAP")
        if duration_ms < MIN_DURATION_MS:
            warnings.append("TOO_SHORT")
        if duration_ms > MAX_DURATION_MS:
            warnings.append("TOO_LONG")
        lines = text.splitlines() or [text]
        if len(lines) > project.style.max_lines:
            warnings.append("TOO_MANY_LINES")
        japanese = project.target_lang == "ja" or (project.target_lang == "none" and is_japanese_text(text))
        max_line = JA_LINE_LIMIT if japanese else EN_LINE_LIMIT
        line_warning = "LINE_TOO_LONG_JA" if japanese else "LINE_TOO_LONG_EN"
        if any(len(line) > max_line for line in lines):
            warnings.append(line_warning)
        cps = reading_cps(text, duration_ms)
        if (japanese and cps > 14) or (not japanese and cps > 20):
            warnings.append("CPS_TOO_HIGH")
        if project.target_lang != "none" and not segment.translated_text:
            warnings.append("TRANSLATION_MISSING")
        font_size = project.style.font_size
        if project.style.font_size_mode == "auto":
            font_size = auto_font_size(project.metadata.width, project.metadata.height)
        if len(lines) * font_size * 1.35 > project.metadata.height * 0.32:
            warnings.append("DISPLAY_MAY_OVERFLOW")
        segment.warnings = sorted(set(warnings))
        previous = segment
    return project


def auto_font_size(width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        return 56
    base = min(width * 0.045, height * 0.075)
    return int(max(22, min(86, round(base))))


def repair_overlaps(segments: List[CaptionSegment]) -> List[CaptionSegment]:
    for idx in range(1, len(segments)):
        prev = segments[idx - 1]
        current = segments[idx]
        if current.locked or prev.locked:
            continue
        max_prev_end = current.start_ms - MIN_GAP_MS
        if prev.end_ms > max_prev_end and max_prev_end > prev.start_ms:
            prev.end_ms = max_prev_end
    return segments
