from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models import CaptionProject, CaptionSegment
from app.services.segmenter import wrap_display_text
from app.services.secrets import load_gemini_api_key
from app.services.storage import ROOT_DIR, save_project


class TranslationError(RuntimeError):
    pass


DEFAULT_BATCH_ITEMS = int(os.getenv("GEMINI_BATCH_ITEMS", "120"))
DEFAULT_BATCH_CHARS = int(os.getenv("GEMINI_BATCH_CHARS", "28000"))
DEFAULT_CONTEXT_SEGMENTS = int(os.getenv("GEMINI_CONTEXT_SEGMENTS", "8"))
DEFAULT_CONCURRENCY = int(os.getenv("GEMINI_TRANSLATION_CONCURRENCY", "3"))


@dataclass(frozen=True)
class BatchTranslation:
    batch_index: int
    count: int
    engine: str
    translations: Dict[int, str]
    error: Optional[str] = None
    warning: Optional[str] = None


def translation_summary(project: CaptionProject) -> Dict[str, object]:
    total = len(project.segments)
    translated = sum(1 for segment in project.segments if segment.translated_text)
    missing = sum(1 for segment in project.segments if not segment.translated_text)
    fallback = sum(1 for record in project.translation_batches if record.get("engine") in {"argos", "source", "gemini_split"})
    warning_count = sum(1 for segment in project.segments if segment.warnings)
    return {
        "total": total,
        "translated": translated,
        "missing": missing,
        "fallback_batches": fallback,
        "warning_segments": warning_count,
        "batches": len(project.translation_batches),
        "last_error": project.last_translation_error,
    }


class Translator:
    name = "base"

    def translate_batch(self, segments: List[CaptionSegment], source_lang: str, target_lang: str) -> Dict[int, str]:
        raise NotImplementedError


def strip_json_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def load_glossary() -> Dict[str, str]:
    path = ROOT_DIR / "glossary.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {}


def make_batches(
    segments: List[CaptionSegment],
    max_items: int = DEFAULT_BATCH_ITEMS,
    max_chars: int = DEFAULT_BATCH_CHARS,
) -> List[List[CaptionSegment]]:
    batches: List[List[CaptionSegment]] = []
    current: List[CaptionSegment] = []
    current_chars = 0
    for segment in segments:
        size = len(format_srt_cue(segment))
        if current and (len(current) >= max_items or current_chars + size > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def ms_to_srt_timestamp(ms: int) -> str:
    value = max(0, int(ms))
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def format_srt_cue(segment: CaptionSegment) -> str:
    text = (segment.source_text or segment.display_text or "").strip()
    return f"{segment.id}\n{ms_to_srt_timestamp(segment.start_ms)} --> {ms_to_srt_timestamp(segment.end_ms)}\n{text}\n"


def format_srt_block(segments: List[CaptionSegment]) -> str:
    return "\n".join(format_srt_cue(segment) for segment in segments).strip()


class GeminiTranslator(Translator):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or load_gemini_api_key()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if not self.api_key:
            raise TranslationError("Gemini API key is not configured")

    def translate_batch(self, segments: List[CaptionSegment], source_lang: str, target_lang: str) -> Dict[int, str]:
        return self.translate_srt_batch(segments, source_lang, target_lang)

    def translate_srt_batch(
        self,
        segments: List[CaptionSegment],
        source_lang: str,
        target_lang: str,
        context_before: Optional[List[CaptionSegment]] = None,
        context_after: Optional[List[CaptionSegment]] = None,
    ) -> Dict[int, str]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise TranslationError("google-genai is not installed") from exc

        glossary = load_glossary()
        prompt = (
            "Translate the TARGET SRT subtitle cues accurately.\n"
            f"Source language: {source_lang}. Target language: {target_lang}.\n"
            "Use cue order and timestamps to understand context, references, tone, and speaker flow.\n"
            "Return only JSON matching the schema.\n"
            "Rules:\n"
            "- Translate every TARGET SRT cue exactly once.\n"
            "- Use the SRT cue number as segment_id.\n"
            "- Do not output context cue translations.\n"
            "- Do not merge, split, omit, renumber, or reorder segment IDs.\n"
            "- Preserve numbers, named entities, product names, and glossary terms unless a glossary says otherwise.\n\n"
            f"Glossary JSON:\n{json.dumps(glossary, ensure_ascii=False)}\n\n"
            f"CONTEXT BEFORE SRT (do not output):\n{format_srt_block(context_before or [])}\n\n"
            f"TARGET SRT:\n{format_srt_block(segments)}\n\n"
            f"CONTEXT AFTER SRT (do not output):\n{format_srt_block(context_after or [])}\n"
        )
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "segment_id": {"type": "integer"},
                            "translated_text": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["segment_id", "translated_text"],
                    },
                }
            },
            "required": ["items"],
        }
        client = genai.Client(api_key=self.api_key)
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.2,
                )
                response = client.models.generate_content(model=self.model, contents=prompt, config=config)
                return validate_translation_response(response.text, segments)
            except Exception as exc:
                last_error = exc
                time.sleep(min(8, 2**attempt))
        raise TranslationError(f"Gemini translation failed: {last_error}")


def validate_translation_response(text: str, segments: List[CaptionSegment]) -> Dict[int, str]:
    try:
        data = json.loads(strip_json_fence(text))
    except json.JSONDecodeError as exc:
        raise TranslationError("Gemini returned invalid JSON") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise TranslationError("Gemini response missing items")
    expected = {s.id for s in segments}
    seen = set()
    output: Dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise TranslationError("Gemini response item is not an object")
        segment_id = item.get("segment_id")
        translated = (item.get("translated_text") or "").strip()
        if segment_id not in expected:
            raise TranslationError(f"Unexpected segment id: {segment_id}")
        if segment_id in seen:
            raise TranslationError(f"Duplicate segment id: {segment_id}")
        if not translated:
            raise TranslationError(f"Empty translation for segment id: {segment_id}")
        source = next((segment.source_text or segment.display_text or "" for segment in segments if segment.id == segment_id), "")
        if source and len(translated) > max(500, len(source) * 8):
            raise TranslationError(f"Abnormally long translation for segment id: {segment_id}")
        seen.add(segment_id)
        output[int(segment_id)] = translated
    if seen != expected:
        raise TranslationError("Gemini response did not cover all segment ids")
    return output


class ArgosTranslator(Translator):
    name = "argos"

    def translate_batch(self, segments: List[CaptionSegment], source_lang: str, target_lang: str) -> Dict[int, str]:
        try:
            import argostranslate.translate
        except ImportError as exc:
            raise TranslationError("argostranslate is not installed") from exc
        output: Dict[int, str] = {}
        for segment in segments:
            text = segment.source_text or segment.display_text
            translated = argostranslate.translate.translate(text, source_lang, target_lang)
            if not translated:
                raise TranslationError(f"Argos returned empty text for segment {segment.id}")
            output[segment.id] = translated
        return output


def batch_context(
    all_segments: List[CaptionSegment],
    batch: List[CaptionSegment],
    context_size: int = DEFAULT_CONTEXT_SEGMENTS,
) -> tuple[List[CaptionSegment], List[CaptionSegment]]:
    if not batch:
        return [], []
    positions = {segment.id: idx for idx, segment in enumerate(all_segments)}
    first = positions.get(batch[0].id, 0)
    last = positions.get(batch[-1].id, first)
    before = all_segments[max(0, first - context_size) : first]
    after = all_segments[last + 1 : last + 1 + context_size]
    return before, after


def translate_batch_with_fallback(
    batch_index: int,
    batch: List[CaptionSegment],
    all_segments: List[CaptionSegment],
    source_lang: str,
    target_lang: str,
    api_key: Optional[str],
    model: str,
) -> BatchTranslation:
    try:
        translations, engine, recovered_error = translate_gemini_with_split(
            batch,
            all_segments,
            source_lang,
            target_lang,
            api_key,
            model,
        )
        warning = "GEMINI_SCHEMA_RETRY" if recovered_error else None
        return BatchTranslation(batch_index=batch_index, count=len(batch), engine=engine, translations=translations, error=recovered_error, warning=warning)
    except Exception as gemini_error:
        try:
            translations = ArgosTranslator().translate_batch(batch, source_lang, target_lang)
            return BatchTranslation(
                batch_index=batch_index,
                count=len(batch),
                engine="argos",
                translations=translations,
                error=str(gemini_error),
                warning="GEMINI_FALLBACK_USED",
            )
        except Exception as argos_error:
            translations = {segment.id: segment.source_text or segment.display_text for segment in batch}
            return BatchTranslation(
                batch_index=batch_index,
                count=len(batch),
                engine="source",
                translations=translations,
                error=f"{gemini_error}; fallback failed: {argos_error}",
                warning="TRANSLATION_MISSING",
            )


def translate_gemini_with_split(
    batch: List[CaptionSegment],
    all_segments: List[CaptionSegment],
    source_lang: str,
    target_lang: str,
    api_key: Optional[str],
    model: str,
    split_depth: int = 1,
) -> tuple[Dict[int, str], str, Optional[str]]:
    try:
        before, after = batch_context(all_segments, batch)
        translations = GeminiTranslator(api_key=api_key, model=model).translate_srt_batch(
            batch,
            source_lang,
            target_lang,
            context_before=before,
            context_after=after,
        )
        return translations, "gemini", None
    except Exception as exc:
        if split_depth <= 0 or len(batch) <= 1:
            raise
        midpoint = len(batch) // 2
        left, _, _ = translate_gemini_with_split(batch[:midpoint], all_segments, source_lang, target_lang, api_key, model, split_depth - 1)
        right, _, _ = translate_gemini_with_split(batch[midpoint:], all_segments, source_lang, target_lang, api_key, model, split_depth - 1)
        return {**left, **right}, "gemini_split", str(exc)


def translation_concurrency(batch_count: int) -> int:
    return max(1, min(batch_count, max(1, DEFAULT_CONCURRENCY), 6))


def emit_progress(progress, pct: float, message: str, current_item: Optional[int] = None, total_items: Optional[int] = None) -> None:
    if not progress:
        return
    try:
        progress(pct, message, current_item, total_items)
    except TypeError:
        progress(pct, message)


def translate_project(
    project: CaptionProject,
    target_lang: str,
    api_key: Optional[str] = None,
    progress=None,
) -> CaptionProject:
    source_lang = project.source_lang if project.source_lang != "auto" else "en"
    project.target_lang = target_lang
    batches = make_batches(project.segments)
    translated_count = 0
    batch_records: List[Optional[Dict[str, object]]] = [None] * len(batches)
    segment_by_id = {segment.id: segment for segment in project.segments}
    workers = translation_concurrency(len(batches))
    completed = 0
    emit_progress(progress, 0, f"翻訳準備: {len(batches)} チャンク / {workers} 並列", 0, len(batches))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                translate_batch_with_fallback,
                index,
                batch,
                project.segments,
                source_lang,
                target_lang,
                api_key,
                project.gemini_model,
            )
            for index, batch in enumerate(batches, 1)
        ]
        for future in as_completed(futures):
            result = future.result()
            for segment_id, translated in result.translations.items():
                segment = segment_by_id.get(segment_id)
                if not segment or not translated:
                    continue
                if result.warning:
                    segment.warnings = sorted(set(segment.warnings + [result.warning]))
                segment.translated_text = translated
                segment.display_text = wrap_display_text(translated, target_lang)
                translated_count += 1
            batch_records[result.batch_index - 1] = {
                "batch_index": result.batch_index,
                "count": result.count,
                "engine": result.engine,
                "error": result.error,
            }
            completed += 1
            project.translation_batches = [record for record in batch_records if record]
            project.translation_summary = translation_summary(project)
            save_project(project)
            emit_progress(
                progress,
                completed / max(1, len(batches)) * 100,
                f"翻訳中 {completed}/{len(batches)} チャンク",
                completed,
                len(batches),
            )
    project.translation_engine = "gemini"
    project.last_translation_error = next((b["error"] for b in reversed(project.translation_batches) if b.get("error")), None)
    project.translation_summary = translation_summary(project)
    emit_progress(progress, 100, f"翻訳完了: {translated_count}/{len(project.segments)} 件", len(batches), len(batches))
    return project


def argos_pair_installed(source_lang: str, target_lang: str) -> bool:
    try:
        import argostranslate.translate
    except ImportError:
        return False
    try:
        installed = argostranslate.translate.get_installed_languages()
        source = next((lang for lang in installed if lang.code == source_lang), None)
        if not source:
            return False
        return any(lang.code == target_lang for lang in source.translations_to)
    except Exception:
        return False
