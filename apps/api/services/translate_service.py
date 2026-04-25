"""Gemini-only translation service with batching, context window and glossary.

Replaces ``utils/translate_utils.py``. DeepL is no longer supported per the
revised plan; one-call-per-line was the dominant cause of (a) translation
inconsistency, (b) rate-limit spikes, and (c) total wall-clock cost.

Design:

* **Batch size 50** by default. The batch JSON is sent in a single
  ``generate_content`` call with ``response_mime_type='application/json'`` and
  a strict response schema, so the model returns a parallel array of
  translations.
* **Context window** of N preceding and N following segments is included in
  the prompt as *unmodified context* — the model sees them but only translates
  the central window.
* **Glossary** entries are included verbatim in the system instruction.
* **Retry**: ``tenacity`` exponential backoff for 429 / 5xx; failures within a
  batch keep the original text and are flagged in the result so the editor can
  surface a ``needs_review`` badge.
* **Re-translate one segment** with optional alternate-candidates for the
  inline editor "AI candidates" UI.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Friendly target-language labels accepted by the API; we map to Gemini-readable names.
LANG_NAMES: dict[str, str] = {
    "ja": "Japanese",
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "ko": "Korean",
    "pt": "Portuguese",
}


class TranslationError(RuntimeError):
    """Raised when the model returns nothing usable after retries."""


@dataclass(slots=True)
class TranslationResult:
    text: str
    needs_review: bool = False
    error: str | None = None


@dataclass(slots=True)
class GlossaryEntry:
    source: str
    target: str
    note: str | None = None


def _system_instruction(
    source_lang: str,
    target_lang: str,
    glossary: Sequence[GlossaryEntry] | None,
    style_hint: str | None,
) -> str:
    src = LANG_NAMES.get(source_lang, source_lang)
    tgt = LANG_NAMES.get(target_lang, target_lang)
    parts = [
        f"You translate subtitle lines from {src} to {tgt}.",
        "Preserve speaker register, idioms, and punctuation when possible.",
        "Output must be plain text only — no quotes, no commentary, no notes.",
        "Each item in the input array is one subtitle line; translate each "
        "independently while keeping the multi-line conversation consistent.",
    ]
    if glossary:
        glossary_lines = "\n".join(
            f"- {g.source} → {g.target}" + (f"  ({g.note})" if g.note else "")
            for g in glossary
        )
        parts.append("Glossary (apply these translations exactly when the source matches):\n" + glossary_lines)
    if style_hint:
        parts.append(f"Style preference: {style_hint}")
    return "\n\n".join(parts)


def _make_prompt(
    central: Sequence[str],
    before: Sequence[str],
    after: Sequence[str],
) -> str:
    payload = {
        "context_before": list(before),
        "translate": list(central),
        "context_after": list(after),
    }
    return (
        "Return JSON of the form {\"translations\": [\"...\", \"...\"]} where the "
        "array length equals the input 'translate' array. Do not include "
        "context_before/context_after in the output.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )


class GeminiTranslator:
    """Thin wrapper around ``google.generativeai`` with the design above."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")
        self._api_key = api_key
        self._model_name = model
        self._temperature = temperature

    # ── public API ──────────────────────────────────────────────────────────

    def translate_segments(
        self,
        texts: Sequence[str],
        *,
        source_lang: str,
        target_lang: str,
        batch_size: int = 50,
        context_window: int = 10,
        glossary: Sequence[GlossaryEntry] | None = None,
        style_hint: str | None = None,
    ) -> list[TranslationResult]:
        """Translate ``texts`` preserving order and length."""
        if source_lang == target_lang:
            return [TranslationResult(text=t) for t in texts]

        results: list[TranslationResult] = [TranslationResult(text=t, needs_review=True) for t in texts]
        n = len(texts)
        for i in range(0, n, batch_size):
            j = min(i + batch_size, n)
            before = texts[max(0, i - context_window) : i]
            after = texts[j : min(n, j + context_window)]
            central = texts[i:j]
            try:
                translated = self._translate_batch(
                    central,
                    before,
                    after,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    glossary=glossary,
                    style_hint=style_hint,
                )
            except Exception as e:
                logger.error("Batch %d-%d failed: %s", i, j, e)
                for k, src in enumerate(central):
                    results[i + k] = TranslationResult(text=src, needs_review=True, error=str(e))
                continue

            if len(translated) != len(central):
                logger.error(
                    "Gemini returned %d items for a batch of %d; falling back to source text",
                    len(translated),
                    len(central),
                )
                for k, src in enumerate(central):
                    results[i + k] = TranslationResult(text=src, needs_review=True, error="length mismatch")
                continue

            for k, t in enumerate(translated):
                results[i + k] = TranslationResult(text=t, needs_review=False)
        return results

    def retranslate_one(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        candidates: int = 3,
        glossary: Sequence[GlossaryEntry] | None = None,
        style_hint: str | None = None,
    ) -> list[str]:
        """Return up to ``candidates`` alternate translations for one line.

        Used by the Inspector's "AI 再翻訳" picker. Higher temperature drives
        diversity.
        """
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=_system_instruction(source_lang, target_lang, glossary, style_hint),
            generation_config={
                "temperature": 0.9,
                "candidate_count": min(8, max(1, candidates)),
            },
        )
        response = model.generate_content(
            f'Translate this subtitle line to {LANG_NAMES.get(target_lang, target_lang)}: "{text}"'
        )
        outputs: list[str] = []
        for cand in getattr(response, "candidates", []) or []:
            try:
                parts = cand.content.parts  # type: ignore[attr-defined]
                outputs.append("".join(p.text for p in parts if hasattr(p, "text")).strip())
            except AttributeError:
                continue
        if not outputs and getattr(response, "text", None):
            outputs.append(response.text.strip())
        # De-dup while preserving order
        seen: set[str] = set()
        unique = [o for o in outputs if not (o in seen or seen.add(o))]
        return unique[:candidates]

    # ── internals ───────────────────────────────────────────────────────────

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(Exception),
    )
    def _translate_batch(
        self,
        central: Sequence[str],
        before: Sequence[str],
        after: Sequence[str],
        *,
        source_lang: str,
        target_lang: str,
        glossary: Sequence[GlossaryEntry] | None,
        style_hint: str | None,
    ) -> list[str]:
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=_system_instruction(source_lang, target_lang, glossary, style_hint),
            generation_config={
                "temperature": self._temperature,
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "translations": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["translations"],
                },
            },
        )
        response = model.generate_content(_make_prompt(central, before, after))
        raw = getattr(response, "text", None)
        if not raw:
            raise TranslationError("Empty response from Gemini")

        data = json.loads(raw)
        translations = data.get("translations")
        if not isinstance(translations, list):
            raise TranslationError(f"Unexpected response shape: {raw[:120]}")
        return [str(t) for t in translations]


def translate_in_place(
    segments: Iterable[object],
    translator: GeminiTranslator,
    *,
    source_lang: str,
    target_lang: str,
    glossary: Sequence[GlossaryEntry] | None = None,
    style_hint: str | None = None,
) -> list[TranslationResult]:
    """Translate the ``text`` attribute of each segment in place.

    The segment objects only need ``.text`` (settable). Returns the translation
    metadata so the caller can surface ``needs_review`` flags in the editor.
    """
    import contextlib

    seg_list = list(segments)
    texts = [getattr(s, "text", "") or "" for s in seg_list]
    results = translator.translate_segments(
        texts,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary=glossary,
        style_hint=style_hint,
    )
    for seg, result in zip(seg_list, results, strict=True):
        # Immutable backend Segments simply skip; caller should re-create them.
        with contextlib.suppress(AttributeError):
            seg.text = result.text  # type: ignore[attr-defined]
    return results
