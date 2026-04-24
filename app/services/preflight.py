from __future__ import annotations

import os
import platform
import sys
import importlib
from pathlib import Path

from app.models import PreflightCheck, PreflightResponse
from app.services import asr
from app.services.secrets import gemini_api_key_status
from app.services.storage import PROJECTS_DIR, ensure_projects_dir
from app.services.translator import argos_pair_installed
from app.services.video import ffmpeg_has_filter, preflight_binary, render_ffmpeg_executable


def run_preflight(gemini_api_key: str = "") -> PreflightResponse:
    checks = []
    checks.append(PreflightCheck(name="python_executable", ok=True, detail=sys.executable))
    checks.append(PreflightCheck(name="python_version", ok=sys.version_info >= (3, 9), detail=platform.python_version()))
    apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    checks.append(
        PreflightCheck(
            name="apple_silicon",
            ok=apple_silicon,
            detail=f"{platform.system()} {platform.machine()}",
        )
    )
    for binary in ("ffmpeg", "ffprobe"):
        ok, detail = preflight_binary(binary)
        checks.append(PreflightCheck(name=binary, ok=ok, detail=detail))
    try:
        ensure_projects_dir()
        probe = PROJECTS_DIR / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(PreflightCheck(name="projects_writable", ok=True, detail=str(PROJECTS_DIR)))
    except Exception as exc:
        checks.append(PreflightCheck(name="projects_writable", ok=False, detail=str(exc)))
    key_status = {"configured": True, "source": "session"} if gemini_api_key else gemini_api_key_status()
    checks.append(
        PreflightCheck(
            name="gemini_api_key",
            ok=bool(key_status["configured"]),
            detail=str(key_status["source"]) if key_status["configured"] else "missing",
        )
    )
    checks.append(PreflightCheck(name="argos_en_ja", ok=argos_pair_installed("en", "ja"), detail="installed language pair"))
    checks.append(PreflightCheck(name="argos_ja_en", ok=argos_pair_installed("ja", "en"), detail="installed language pair"))
    for module_name in ("mlx", "mlx_whisper"):
        try:
            module = importlib.import_module(module_name)
            detail = getattr(module, "__version__", "installed")
            checks.append(PreflightCheck(name=module_name, ok=True, detail=str(detail)))
        except Exception as exc:
            checks.append(PreflightCheck(name=module_name, ok=False, detail=str(exc)))
    for status in asr.backend_status("fast"):
        checks.append(PreflightCheck(name=f"asr_backend_{status.name}", ok=status.available, detail=f"{status.detail}; model={status.model}"))
    cache_ok, cache_detail = asr.mlx_cache_status()
    checks.append(PreflightCheck(name="mlx_model_cache", ok=cache_ok, detail=cache_detail if cache_ok else f"not downloaded yet: {cache_detail}"))
    selected = asr.selected_backend_name("auto")
    checks.append(PreflightCheck(name="asr_engine", ok=selected != "unavailable", detail=selected))
    render_ffmpeg = render_ffmpeg_executable()
    render_ok = ffmpeg_has_filter(render_ffmpeg, "ass") or ffmpeg_has_filter(render_ffmpeg, "subtitles")
    checks.append(PreflightCheck(name="subtitle_render_filter", ok=render_ok, detail=render_ffmpeg))
    try:
        import yt_dlp

        checks.append(PreflightCheck(name="yt_dlp", ok=True, detail=getattr(yt_dlp.version, "__version__", "installed")))
    except Exception as exc:
        checks.append(PreflightCheck(name="yt_dlp", ok=False, detail=str(exc)))
    venv_python = Path(".venv/bin/python")
    if venv_python.is_symlink() and not venv_python.exists():
        checks.append(PreflightCheck(name="venv", ok=False, detail=f"{venv_python} is a broken symlink"))
    else:
        checks.append(PreflightCheck(name="venv", ok=True, detail="not broken or not present"))
    return PreflightResponse(checks=checks, gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
