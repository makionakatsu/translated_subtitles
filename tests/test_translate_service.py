"""Unit tests for the Gemini translation service.

The Gemini SDK is stubbed in ``conftest.py``; here we monkey-patch
``GenerativeModel`` per-test so the prompt and response shape are deterministic.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any, ClassVar

import pytest

from apps.api.services.translate_service import (
    GeminiTranslator,
    GlossaryEntry,
    TranslationResult,
)


class _FakeModel:
    """Records prompts and returns whatever batch the test programmed.

    A single class-level program queue is shared so each freshly constructed
    ``GenerativeModel`` (one per batch in :class:`GeminiTranslator`) picks up
    the next programmed response in order.
    """

    instances: ClassVar[list[_FakeModel]] = []
    program_queue: ClassVar[list[Any]] = []

    def __init__(self, model_name: str, **kwargs: Any) -> None:
        self.model_name = model_name
        self.kwargs = kwargs
        self.system_instruction = kwargs.get("system_instruction")
        self.calls: list[str] = []
        _FakeModel.instances.append(self)

    @classmethod
    def program(cls, *responses: Any) -> None:
        cls.program_queue.extend(responses)

    def generate_content(self, prompt: str) -> Any:
        self.calls.append(prompt)
        if not _FakeModel.program_queue:
            raise AssertionError("FakeModel has no programmed response")
        return _FakeModel.program_queue.pop(0)


@pytest.fixture(autouse=True)
def _patch_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeModel.instances.clear()
    _FakeModel.program_queue.clear()
    genai = sys.modules["google.generativeai"]
    monkeypatch.setattr(genai, "GenerativeModel", _FakeModel)
    monkeypatch.setattr(genai, "configure", lambda **kw: None)


def _resp(translations: list[str]) -> Any:
    text = json.dumps({"translations": translations}, ensure_ascii=False)
    return types.SimpleNamespace(text=text, candidates=[])


def test_translate_segments_batches_and_preserves_order() -> None:
    translator = GeminiTranslator(api_key="fake")
    texts = [f"line {i}" for i in range(75)]
    _FakeModel.program(
        _resp([f"訳 {i}" for i in range(50)]),
        _resp([f"訳 {i}" for i in range(50, 75)]),
    )

    results = translator.translate_segments(
        texts,
        source_lang="en",
        target_lang="ja",
        batch_size=50,
    )

    assert len(results) == 75
    assert results[0].text == "訳 0"
    assert results[49].text == "訳 49"
    assert results[50].text == "訳 50"
    assert all(not r.needs_review for r in results)


def test_translate_segments_marks_failed_batch_for_review() -> None:
    translator = GeminiTranslator(api_key="fake")
    texts = ["a", "b", "c"]
    # Wrong shape: an extra item — service must keep originals and flag review.
    _FakeModel.program(_resp(["A", "B", "C", "D"]))

    results = translator.translate_segments(texts, source_lang="en", target_lang="ja")
    assert [r.text for r in results] == texts
    assert all(r.needs_review for r in results)


def test_skip_translation_when_languages_match() -> None:
    translator = GeminiTranslator(api_key="fake")
    results = translator.translate_segments(["hi"], source_lang="en", target_lang="en")
    assert results == [TranslationResult(text="hi")]


def test_glossary_appears_in_system_instruction() -> None:
    translator = GeminiTranslator(api_key="fake")
    _FakeModel.program(_resp(["こんにちは"]))

    translator.translate_segments(
        ["hello"],
        source_lang="en",
        target_lang="ja",
        glossary=[GlossaryEntry(source="hello", target="こんにちは", note="greeting")],
    )

    assert _FakeModel.instances, "GenerativeModel was not constructed"
    inst = _FakeModel.instances[0]
    assert "Glossary" in inst.system_instruction
    assert "hello → こんにちは" in inst.system_instruction


def test_context_window_present_in_prompt() -> None:
    translator = GeminiTranslator(api_key="fake")
    # batch_size=1 → 5 batches, each returns one translation.
    _FakeModel.program(*[_resp([f"訳{i}"]) for i in range(5)])

    texts = ["before2", "before1", "central", "after1", "after2"]
    translator.translate_segments(
        texts,
        source_lang="en",
        target_lang="ja",
        batch_size=1,
        context_window=2,
    )

    # The third batch (i=2, "central") should see the two preceding lines as
    # context_before and the two following lines as context_after.
    inst_for_central = _FakeModel.instances[2]
    central_prompt = inst_for_central.calls[0]
    assert '"context_before": ["before2", "before1"]' in central_prompt
    assert '"translate": ["central"]' in central_prompt
    assert '"context_after": ["after1", "after2"]' in central_prompt
