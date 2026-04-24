from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple


MODEL_CACHE: Dict[str, Any] = {}


MLX_PRESETS = {
    "fast": os.getenv("MLX_WHISPER_MODEL_FAST", "mlx-community/whisper-small-mlx"),
    "balanced": os.getenv("MLX_WHISPER_MODEL_BALANCED", "mlx-community/whisper-medium-mlx"),
    "quality": os.getenv("MLX_WHISPER_MODEL_QUALITY", "mlx-community/whisper-large-v3-mlx"),
}

FASTER_PRESETS = {
    "fast": {"model_size": "small", "compute_type": "int8", "beam_size": 1},
    "balanced": {"model_size": "medium", "compute_type": "int8", "beam_size": 3},
    "quality": {"model_size": "medium", "compute_type": "int8", "beam_size": 5},
}


class ASRError(RuntimeError):
    pass


class ASRBackend(Protocol):
    name: str

    def available(self) -> bool:
        ...

    def model_for_preset(self, preset: str) -> str:
        ...

    def transcribe(self, audio_path: str, preset: str, source_lang: str) -> Tuple[Iterable[Any], Any, Dict[str, float]]:
        ...


@dataclass(frozen=True)
class BackendStatus:
    name: str
    available: bool
    detail: str
    model: str


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _language(source_lang: str) -> Optional[str]:
    return None if source_lang == "auto" else source_lang


def _audio_duration_from_result(result: Dict[str, Any]) -> Optional[float]:
    for key in ("duration", "audio_duration"):
        value = result.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def normalize_mlx_segments(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in result.get("segments", []) or []:
        if not isinstance(item, dict):
            continue
        words = []
        for word in item.get("words", []) or []:
            if isinstance(word, dict):
                words.append({"start": word.get("start"), "end": word.get("end"), "word": word.get("word") or word.get("text") or ""})
            else:
                words.append(word)
        normalized.append(
            {
                "start": item.get("start"),
                "end": item.get("end"),
                "text": item.get("text") or "",
                "words": words,
            }
        )
    return normalized


class MlxWhisperBackend:
    name = "mlx"

    def available(self) -> bool:
        if not is_apple_silicon():
            return False
        try:
            import mlx_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def model_for_preset(self, preset: str) -> str:
        return MLX_PRESETS.get(preset, MLX_PRESETS["fast"])

    def transcribe(self, audio_path: str, preset: str, source_lang: str) -> Tuple[Iterable[Any], Any, Dict[str, float]]:
        try:
            import mlx_whisper
        except ImportError as exc:
            raise ASRError("mlx-whisper is not installed") from exc
        if not is_apple_silicon():
            raise ASRError("mlx-whisper is only enabled on Apple Silicon macOS")
        model = self.model_for_preset(preset)
        started = time.monotonic()
        kwargs: Dict[str, Any] = {"path_or_hf_repo": model, "word_timestamps": True, "condition_on_previous_text": False}
        language = _language(source_lang)
        if language:
            kwargs["language"] = language
        result = mlx_whisper.transcribe(audio_path, **kwargs)
        elapsed = time.monotonic() - started
        if not isinstance(result, dict):
            raise ASRError("mlx-whisper returned an unexpected result")
        segments = normalize_mlx_segments(result)
        audio_duration = _audio_duration_from_result(result)
        info = SimpleNamespace(
            language=result.get("language") or source_lang or "auto",
            asr_engine=self.name,
            asr_model=model,
            asr_device="mlx",
            asr_duration_sec=elapsed,
            audio_duration_sec=audio_duration,
        )
        timings = {"asr_sec": elapsed}
        if audio_duration and audio_duration > 0:
            timings["asr_rtf"] = elapsed / audio_duration
        return segments, info, timings


class FasterWhisperBackend:
    name = "faster-whisper"

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def model_for_preset(self, preset: str) -> str:
        config = FASTER_PRESETS.get(preset, FASTER_PRESETS["fast"])
        return str(config["model_size"])

    def get_model(self, model_size: str, compute_type: str = "int8", device: str = "cpu") -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRError("faster-whisper is not installed") from exc
        key = f"{model_size}:{device}:{compute_type}"
        if key not in MODEL_CACHE:
            MODEL_CACHE[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
        return MODEL_CACHE[key]

    def transcribe(self, audio_path: str, preset: str, source_lang: str) -> Tuple[Iterable[Any], Any, Dict[str, float]]:
        config = FASTER_PRESETS.get(preset, FASTER_PRESETS["fast"])
        started = time.monotonic()
        model = self.get_model(config["model_size"], config["compute_type"])
        language = _language(source_lang)
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=config["beam_size"],
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        elapsed = time.monotonic() - started
        materialized = list(segments)
        setattr(info, "asr_engine", self.name)
        setattr(info, "asr_model", str(config["model_size"]))
        setattr(info, "asr_device", "cpu")
        setattr(info, "asr_duration_sec", elapsed)
        return materialized, info, {"asr_sec": elapsed}


BACKENDS: Dict[str, ASRBackend] = {
    "mlx": MlxWhisperBackend(),
    "faster-whisper": FasterWhisperBackend(),
}


def backend_status(preset: str = "fast") -> List[BackendStatus]:
    statuses: List[BackendStatus] = []
    for name, backend in BACKENDS.items():
        try:
            available = backend.available()
            detail = "available" if available else "not available"
        except Exception as exc:
            available = False
            detail = str(exc)
        statuses.append(BackendStatus(name=name, available=available, detail=detail, model=backend.model_for_preset(preset)))
    return statuses


def select_backend(asr_engine: str = "auto") -> ASRBackend:
    requested = asr_engine or "auto"
    if requested != "auto":
        backend = BACKENDS.get(requested)
        if not backend:
            raise ASRError(f"Unknown ASR engine: {requested}")
        if not backend.available():
            raise ASRError(f"ASR engine is not available: {requested}")
        return backend
    for name in ("mlx", "faster-whisper"):
        backend = BACKENDS[name]
        if backend.available():
            return backend
    raise ASRError("No ASR backend is available. Install mlx-whisper or faster-whisper.")


def selected_backend_name(asr_engine: str = "auto") -> str:
    try:
        return select_backend(asr_engine).name
    except Exception:
        return "unavailable"


def model_for_request(preset: str = "fast", asr_engine: str = "auto") -> str:
    try:
        return select_backend(asr_engine).model_for_preset(preset)
    except Exception:
        if asr_engine in BACKENDS:
            return BACKENDS[asr_engine].model_for_preset(preset)
        return MLX_PRESETS.get(preset, MLX_PRESETS["fast"])


def mlx_cache_status() -> tuple[bool, str]:
    candidates = []
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        candidates.append(Path(hf_home) / "hub")
    candidates.append(Path.home() / ".cache" / "huggingface" / "hub")
    existing = [path for path in candidates if path.exists()]
    if existing:
        return True, ", ".join(str(path) for path in existing)
    return False, str(candidates[-1])


def transcribe(
    audio_path: str,
    preset: str = "fast",
    source_lang: str = "auto",
    asr_engine: str = "auto",
) -> Tuple[Iterable[Any], Any, Dict[str, float]]:
    backend = select_backend(asr_engine)
    try:
        return backend.transcribe(audio_path, preset, source_lang)
    except Exception:
        if asr_engine == "auto" and backend.name == "mlx" and BACKENDS["faster-whisper"].available():
            return BACKENDS["faster-whisper"].transcribe(audio_path, preset, source_lang)
        raise
