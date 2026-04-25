"""Shared pytest fixtures.

We stub the heavy / Mac-incompatible imports so snapshot tests run on a minimal
Python environment (CI Linux, no streamlit / torch / faster-whisper). Only the
pure subtitle-format writers are exercised here.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ── Stub heavy imports BEFORE utils/* gets imported ─────────────────────────
def _install_stub(name: str, attrs: dict[str, object] | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod


class _StreamlitStub:
    def __getattr__(self, item: str):
        def _noop(*a, **kw):
            class _Empty:
                def progress(self, *a, **kw):
                    return None

                def text(self, *a, **kw):
                    return None

                def empty(self):
                    return None

            return _Empty()

        return _noop


sys.modules.setdefault("streamlit", _StreamlitStub())  # type: ignore[arg-type]
_install_stub("ffmpeg", {"probe": lambda *a, **kw: {"streams": [], "format": {}}, "Error": Exception})
_install_stub("yt_dlp", {"YoutubeDL": object, "utils": types.SimpleNamespace(DownloadError=Exception)})
_install_stub("deepl", {"Translator": object, "QuotaExceededException": Exception, "DeepLException": Exception})

# google.generativeai
google_pkg = types.ModuleType("google")
genai_mod = types.ModuleType("google.generativeai")
genai_mod.configure = lambda **kw: None  # type: ignore[attr-defined]
genai_mod.GenerativeModel = object  # type: ignore[attr-defined]
google_pkg.generativeai = genai_mod  # type: ignore[attr-defined]
sys.modules.setdefault("google", google_pkg)
sys.modules.setdefault("google.generativeai", genai_mod)

_install_stub("faster_whisper", {"WhisperModel": object})


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
