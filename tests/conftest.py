"""Shared pytest fixtures and lightweight stubs.

CI Linux runs without the Apple-Silicon-only ``mlx-whisper`` package and
without the heavyweight ``faster-whisper`` model files. Optional native deps
(``ffmpeg-python``, ``yt-dlp``) are also stubbed so unit tests stay hermetic.
Real integration tests live in a separate suite (Phase 6+).
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _install_stub(name: str, attrs: dict[str, object] | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_install_stub(
    "ffmpeg",
    {"probe": lambda *_a, **_kw: {"streams": [], "format": {}}, "Error": Exception},
)
_install_stub(
    "yt_dlp",
    {
        "YoutubeDL": object,
        "utils": types.SimpleNamespace(DownloadError=Exception),
    },
)
_install_stub(
    "mlx_whisper",
    {"transcribe": lambda *_a, **_kw: {"segments": [], "language": "en"}},
)
_install_stub("faster_whisper", {"WhisperModel": object})

# google.generativeai is patched per-test in test_translate_service.py; here we
# just install enough so importing apps.api.services.translate_service works.
google_pkg = types.ModuleType("google")
genai_mod = types.ModuleType("google.generativeai")
genai_mod.configure = lambda **_kw: None  # type: ignore[attr-defined]


class _StubModel:
    def __init__(self, *_a, **_kw) -> None:
        self._responses: list[object] = []

    def generate_content(self, *_a, **_kw):  # type: ignore[no-untyped-def]
        return types.SimpleNamespace(text='{"translations": []}', candidates=[])


genai_mod.GenerativeModel = _StubModel  # type: ignore[attr-defined]
google_pkg.generativeai = genai_mod  # type: ignore[attr-defined]
sys.modules.setdefault("google", google_pkg)
sys.modules.setdefault("google.generativeai", genai_mod)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Rewrite the snapshot files on disk instead of comparing.",
    )


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str


@pytest.fixture
def sample_segments() -> list[FakeSegment]:
    """Stable, hand-crafted segments covering edge cases."""
    return [
        FakeSegment(start=0.0, end=1.234, text="Hello, world."),
        FakeSegment(start=1.5, end=4.0, text="こんにちは、世界。\nThis line wraps."),
        FakeSegment(start=4.0, end=4.05, text="!"),
        FakeSegment(start=10.0, end=12.5, text="日本語と English の混在テスト"),
        FakeSegment(start=3599.5, end=3601.25, text="Crossing the hour boundary."),
    ]
