from __future__ import annotations

import re
import textwrap
from typing import Any, Iterable, List, Optional

from app.models import CaptionSegment
from app.services.quality import MAX_DURATION_MS, MIN_DURATION_MS, repair_overlaps


PUNCTUATION = tuple("。！？.!?")


def _getattr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def ms(value: Optional[float]) -> int:
    return int(round(max(0.0, float(value or 0.0)) * 1000))


def _segment_words(raw_segments: Iterable[Any]) -> List[dict]:
    words: List[dict] = []
    for segment in raw_segments:
        for word in _getattr_or_key(segment, "words", []) or []:
            start = _getattr_or_key(word, "start")
            end = _getattr_or_key(word, "end")
            text = _getattr_or_key(word, "word", "")
            if start is None or end is None or not text:
                continue
            words.append({"start_ms": ms(start), "end_ms": ms(end), "text": str(text)})
    return words


def _fallback_segments(raw_segments: Iterable[Any]) -> List[CaptionSegment]:
    output: List[CaptionSegment] = []
    for idx, segment in enumerate(raw_segments, 1):
        text = normalize_text(_getattr_or_key(segment, "text", ""))
        if not text:
            continue
        output.append(
            CaptionSegment(
                id=idx,
                start_ms=ms(_getattr_or_key(segment, "start", 0.0)),
                end_ms=ms(_getattr_or_key(segment, "end", 0.0)),
                source_text=text,
                display_text=wrap_display_text(text, "auto"),
            )
        )
    return repair_overlaps(output)


def should_break(text: str, start_ms: int, current_end_ms: int, next_start_ms: Optional[int], language: str) -> bool:
    duration = current_end_ms - start_ms
    limit = 24 if language == "ja" else 54
    if next_start_ms is not None and next_start_ms - current_end_ms >= 700 and duration >= MIN_DURATION_MS:
        return True
    if duration >= MAX_DURATION_MS:
        return True
    stripped = text.strip()
    if stripped.endswith(PUNCTUATION) and duration >= MIN_DURATION_MS:
        return True
    return len(stripped) >= limit and duration >= MIN_DURATION_MS


def build_segments(raw_segments: Iterable[Any], language: str = "auto") -> List[CaptionSegment]:
    raw_list = list(raw_segments)
    words = _segment_words(raw_list)
    if not words:
        return _fallback_segments(raw_list)
    output: List[CaptionSegment] = []
    start_ms = words[0]["start_ms"]
    end_ms = words[0]["end_ms"]
    text_parts: List[str] = []
    next_id = 1
    for idx, word in enumerate(words):
        text_parts.append(word["text"])
        end_ms = word["end_ms"]
        current_text = normalize_text("".join(text_parts))
        next_word = words[idx + 1] if idx + 1 < len(words) else None
        if should_break(current_text, start_ms, end_ms, next_word["start_ms"] if next_word else None, language):
            display = wrap_display_text(current_text, language)
            output.append(
                CaptionSegment(
                    id=next_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_text=current_text,
                    display_text=display,
                )
            )
            next_id += 1
            text_parts = []
            if next_word:
                start_ms = next_word["start_ms"]
    if text_parts:
        current_text = normalize_text("".join(text_parts))
        output.append(
            CaptionSegment(
                id=next_id,
                start_ms=start_ms,
                end_ms=end_ms,
                source_text=current_text,
                display_text=wrap_display_text(current_text, language),
            )
        )
    return repair_overlaps(output)


def wrap_display_text(text: str, language: str, max_lines: int = 2) -> str:
    text = normalize_text(text)
    if not text:
        return ""
    if language == "ja" or any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in text):
        width = 22
        lines = [text[i : i + width] for i in range(0, len(text), width)]
    else:
        lines = textwrap.wrap(text, width=42, break_long_words=False, replace_whitespace=True)
    return "\n".join(lines[:max_lines])
