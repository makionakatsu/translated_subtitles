from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import CaptionProject, CaptionSegment, GeminiKeyRequest, GenerateRequest, RenderRequest, SegmentPatch, SegmentSplitRequest, TranslateRequest, TranscribeRequest
from app.services import asr
from app.services.jobs import JobContext, job_manager
from app.services.preflight import run_preflight
from app.services.quality import apply_quality
from app.services.render import burn_mp4, burn_preview_mp4, write_ass, write_bilingual_ass, write_srt, write_vtt
from app.services.render import RenderError
from app.services.segmenter import build_segments
from app.services.segmenter import wrap_display_text
from app.services.secrets import delete_gemini_api_key, gemini_api_key_status, save_gemini_api_key
from app.services.storage import (
    artifact_path,
    artifact_urls,
    create_project,
    load_project,
    new_project_id,
    project_dir,
    save_project,
    sanitize_filename,
)
from app.services.translator import translate_project, translation_summary
from app.services.video import MediaError, extract_audio, probe_media
from app.services.video import download_url, is_supported_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    job_manager.start()
    yield


app = FastAPI(title="Local Caption MVP", lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/preflight")
async def preflight(x_gemini_api_key: Optional[str] = Header(default=None)):
    return run_preflight(x_gemini_api_key or "")


@app.get("/api/settings")
async def settings():
    return {"gemini_api_key": gemini_api_key_status()}


@app.post("/api/settings/gemini-key")
async def set_gemini_key(request: GeminiKeyRequest):
    try:
        source = save_gemini_api_key(request.api_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"gemini_api_key": {"configured": True, "source": source}}


@app.delete("/api/settings/gemini-key")
async def clear_gemini_key():
    delete_gemini_api_key()
    return {"gemini_api_key": gemini_api_key_status()}


@app.post("/api/projects")
async def create_project_endpoint(
    video_file: Optional[UploadFile] = File(default=None),
    local_path: Optional[str] = Form(default=None),
):
    if video_file is None and not local_path:
        raise HTTPException(status_code=400, detail="video_file or local_path is required")
    try:
        if local_path:
            if is_supported_url(local_path):
                project_id = new_project_id()
                directory = project_dir(project_id)
                directory.mkdir(parents=True, exist_ok=False)
                path = download_url(local_path, directory)
                metadata = probe_media(path)
                project = CaptionProject(
                    id=project_id,
                    video_path=str(path),
                    video_name=path.name,
                    metadata=metadata,
                )
                save_project(project)
            else:
                path = Path(local_path).expanduser().resolve()
                metadata = probe_media(path)
                project = create_project(path, metadata)
        else:
            assert video_file is not None
            project_id = new_project_id()
            directory = project_dir(project_id)
            directory.mkdir(parents=True, exist_ok=False)
            safe_name = sanitize_filename(video_file.filename or "source")
            suffix = Path(safe_name).suffix or ".bin"
            path = directory / f"source{suffix}"
            path.write_bytes(await video_file.read())
            metadata = probe_media(path)
            project = CaptionProject(
                id=project_id,
                video_path=str(path),
                video_name=safe_name,
                metadata=metadata,
            )
            save_project(project)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"project_id": project.id, "project": project, "artifacts": artifact_urls(project)}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    project = _load_or_404(project_id)
    return {"project": project, "artifacts": artifact_urls(project)}


@app.get("/api/projects/{project_id}/video")
async def get_project_video(project_id: str) -> FileResponse:
    project = _load_or_404(project_id)
    path = Path(project.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="video not found")
    return FileResponse(path)


@app.get("/api/projects/{project_id}/artifacts/{filename}")
async def get_artifact(project_id: str, filename: str) -> FileResponse:
    project = _load_or_404(project_id)
    allowed = {Path(value).name: value for value in project.artifacts.values() if value}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="artifact not found")
    path = Path(allowed[filename])
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, filename=path.name)


@app.post("/api/projects/{project_id}/transcribe")
async def transcribe_project(project_id: str, request: TranscribeRequest):
    _load_or_404(project_id)

    async def task(context: JobContext):
        try:
            project = load_project(project_id)
            project.source_lang = request.source_lang
            await context.update(5, "Extracting audio")
            audio_path = artifact_path(project_id, "audio.wav")
            await asyncio.to_thread(extract_audio, Path(project.video_path), audio_path, context.check_cancel)
            selected_engine = asr.selected_backend_name(request.asr_engine)
            selected_model = asr.model_for_request(request.preset, request.asr_engine)
            await context.update(18, f"Preparing ASR: {selected_engine} / {selected_model}")
            await context.update(25, "Transcribing")
            raw_segments, info, timings = await asyncio.to_thread(
                asr.transcribe,
                str(audio_path),
                request.preset,
                request.source_lang,
                request.asr_engine,
            )
            context.check_cancel()
            language = getattr(info, "language", None) or request.source_lang or "auto"
            project.source_lang = language
            project.asr_engine = getattr(info, "asr_engine", request.asr_engine)
            project.asr_model = getattr(info, "asr_model", "")
            project.asr_device = getattr(info, "asr_device", "")
            project.asr_duration_sec = getattr(info, "asr_duration_sec", timings.get("asr_sec"))
            project.stage_timings.update(timings)
            if project.metadata.duration_ms and project.asr_duration_sec:
                project.stage_timings["asr_rtf"] = project.asr_duration_sec / (project.metadata.duration_ms / 1000.0)
            await context.update(82, "QC and segmenting captions")
            project.segments = build_segments(raw_segments, language)
            project.status = "transcribed"
            apply_quality(project)
            save_project(project)
            await context.update(100, "Transcription complete")
            return {"project": project.model_dump(), "artifacts": artifact_urls(project)}
        except Exception:
            _mark_failed(project_id)
            raise

    job = await job_manager.submit("transcribe", project_id, task)
    return {"job_id": job.id}


@app.post("/api/projects/{project_id}/generate")
async def generate_project(project_id: str, request: GenerateRequest):
    _load_or_404(project_id)

    async def task(context: JobContext):
        try:
            project = load_project(project_id)
            project.generation_plan = {
                "preset": request.preset,
                "source_lang": request.source_lang,
                "target_lang": request.target_lang,
                "asr_engine": request.asr_engine,
                "translate_mode": request.translate_mode,
            }
            project.generation_status = {"stage": "prepare", "message": "動画準備中"}
            save_project(project)

            await context.update(3, "動画準備中", stage="prepare", stage_label="動画準備", stage_progress=20)
            project.source_lang = request.source_lang

            await context.update(8, "音声抽出中", stage="audio", stage_label="音声抽出", stage_progress=5)
            audio_path = artifact_path(project_id, "audio.wav")
            await asyncio.to_thread(extract_audio, Path(project.video_path), audio_path, context.check_cancel)

            selected_engine = asr.selected_backend_name(request.asr_engine)
            selected_model = asr.model_for_request(request.preset, request.asr_engine)
            await context.update(
                18,
                f"ASR準備中: {selected_engine} / {selected_model}",
                stage="asr_prepare",
                stage_label="ASR準備",
                stage_progress=40,
            )

            await context.update(26, "文字起こし中", stage="asr", stage_label="文字起こし", stage_progress=0)
            raw_segments, info, timings = await asyncio.to_thread(
                asr.transcribe,
                str(audio_path),
                request.preset,
                request.source_lang,
                request.asr_engine,
            )
            context.check_cancel()
            language = getattr(info, "language", None) or request.source_lang or "auto"
            project.source_lang = language
            project.asr_engine = getattr(info, "asr_engine", request.asr_engine)
            project.asr_model = getattr(info, "asr_model", "")
            project.asr_device = getattr(info, "asr_device", "")
            project.asr_duration_sec = getattr(info, "asr_duration_sec", timings.get("asr_sec"))
            project.stage_timings.update(timings)
            if project.metadata.duration_ms and project.asr_duration_sec:
                project.stage_timings["asr_rtf"] = project.asr_duration_sec / (project.metadata.duration_ms / 1000.0)

            await context.update(56, "字幕分割と品質確認中", stage="segment", stage_label="字幕分割", stage_progress=25)
            project.segments = build_segments(raw_segments, language)
            project.status = "transcribed"
            apply_quality(project)
            project.translation_summary = translation_summary(project)
            save_project(project)

            decision = translation_decision(project.source_lang, request.target_lang, request.translate_mode)
            project.target_lang = request.target_lang
            project.generation_status = {
                "stage": "translate_decision",
                "message": decision["reason"],
                "translate": decision["translate"],
            }
            save_project(project)
            if decision["translate"]:
                loop = asyncio.get_running_loop()
                translate_started = time.monotonic()

                def progress(pct: float, message: str, current_item=None, total_items=None) -> None:
                    eta = None
                    if current_item and total_items and current_item > 0:
                        elapsed = time.monotonic() - translate_started
                        eta = (elapsed / current_item) * max(0, total_items - current_item)
                    overall = 62 + (float(pct) * 0.32)
                    stage_progress = float(pct)
                    text = message
                    if current_item is not None and total_items is not None:
                        text = f"{message} ({current_item}/{total_items})"
                    asyncio.run_coroutine_threadsafe(
                        context.update(
                            overall,
                            text,
                            stage="translate",
                            stage_label="Gemini翻訳",
                            stage_progress=stage_progress,
                            current_item=current_item,
                            total_items=total_items,
                            eta_sec=eta,
                        ),
                        loop,
                    )

                await context.update(
                    62,
                    "Gemini翻訳を開始します",
                    stage="translate",
                    stage_label="Gemini翻訳",
                    stage_progress=0,
                    current_item=0,
                    total_items=None,
                )
                project = await asyncio.to_thread(translate_project, project, request.target_lang, request.api_key, progress)
                context.check_cancel()
                project.status = "translated"
                apply_quality(project)
                project.translation_summary = translation_summary(project)
                project.generation_status = {"stage": "translated", "message": "翻訳完了", "translate": True}
                save_project(project)
            else:
                project.translation_batches = []
                project.translation_summary = translation_summary(project)
                project.generation_status = {"stage": "translation_skipped", "message": decision["reason"], "translate": False}
                save_project(project)
                await context.update(86, decision["reason"], stage="translate_skip", stage_label="翻訳判定", stage_progress=100)

            await context.update(96, "品質チェック中", stage="quality", stage_label="品質チェック", stage_progress=70)
            apply_quality(project)
            project.translation_summary = translation_summary(project)
            warning_count = sum(1 for segment in project.segments if segment.warnings)
            project.generation_status = {
                "stage": "done",
                "message": _generation_complete_message(project, warning_count),
                "translate": decision["translate"],
            }
            project.status = "translated" if decision["translate"] else "transcribed"
            save_project(project)
            await context.update(
                100,
                project.generation_status["message"],
                stage="done",
                stage_label="完了",
                stage_progress=100,
                warnings=[f"警告 {warning_count}件"] if warning_count else [],
            )
            return {"project": project.model_dump(), "artifacts": artifact_urls(project)}
        except Exception:
            _mark_failed(project_id)
            raise

    job = await job_manager.submit("generate", project_id, task)
    return {"job_id": job.id}


@app.post("/api/projects/{project_id}/translate")
async def translate_project_endpoint(project_id: str, request: TranslateRequest):
    initial_project = _load_or_404(project_id)
    if not initial_project.segments:
        raise HTTPException(status_code=400, detail="先に文字起こしを実行してください。翻訳する字幕がまだありません。")
    if request.target_lang == "none":
        raise HTTPException(status_code=400, detail="翻訳先言語を選択してください。")

    async def task(context: JobContext):
        try:
            project = load_project(project_id)
            loop = asyncio.get_running_loop()

            def progress(pct: float, message: str) -> None:
                asyncio.run_coroutine_threadsafe(context.update(pct, message), loop)

            await context.update(2, "Translating")
            project = await asyncio.to_thread(translate_project, project, request.target_lang, request.api_key, progress)
            context.check_cancel()
            project.status = "translated"
            apply_quality(project)
            project.translation_summary = translation_summary(project)
            save_project(project)
            await context.update(100, "Translation complete")
            return {"project": project.model_dump(), "artifacts": artifact_urls(project)}
        except Exception:
            _mark_failed(project_id)
            raise

    job = await job_manager.submit("translate", project_id, task)
    return {"job_id": job.id}


@app.patch("/api/projects/{project_id}/segments")
async def patch_segments(project_id: str, patches: list[SegmentPatch]):
    project = _load_or_404(project_id)
    by_id = {segment.id: segment for segment in project.segments}
    for patch in patches:
        segment = by_id.get(patch.id)
        if not segment:
            continue
        if patch.start_ms is not None:
            segment.start_ms = max(0, patch.start_ms)
        if patch.end_ms is not None:
            segment.end_ms = max(0, patch.end_ms)
        if patch.display_text is not None:
            segment.display_text = patch.display_text
        if patch.locked is not None:
            segment.locked = patch.locked
    project.status = "edited"
    apply_quality(project)
    save_project(project)
    return {"project": project, "artifacts": artifact_urls(project)}


@app.post("/api/projects/{project_id}/segments/{segment_id}/split")
async def split_segment(project_id: str, segment_id: int, request: SegmentSplitRequest):
    project = _load_or_404(project_id)
    index = next((idx for idx, segment in enumerate(project.segments) if segment.id == segment_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="segment not found")
    segment = project.segments[index]
    if segment.locked:
        raise HTTPException(status_code=400, detail="locked segment cannot be split")
    split_at = request.at_ms or (segment.start_ms + segment.end_ms) // 2
    if split_at <= segment.start_ms + 200 or split_at >= segment.end_ms - 200:
        raise HTTPException(status_code=400, detail="split point is too close to segment edge")
    original_end_ms = segment.end_ms
    text = segment.display_text or segment.translated_text or segment.source_text
    midpoint = max(1, min(len(text) - 1, len(text) // 2)) if text else 0
    left_text = text[:midpoint].strip() or text.strip()
    right_text = text[midpoint:].strip() or text.strip()
    target_lang = project.target_lang if project.target_lang != "none" else project.source_lang
    segment.end_ms = split_at
    segment.display_text = wrap_display_text(left_text, target_lang)
    segment.translated_text = None
    segment.source_text = left_text
    new_segment = CaptionSegment(
        id=segment.id + 1,
        start_ms=split_at + 40,
        end_ms=original_end_ms,
        source_text=right_text,
        display_text=wrap_display_text(right_text, target_lang),
    )
    project.segments.insert(index + 1, new_segment)
    _renumber_segments(project)
    project.status = "edited"
    apply_quality(project)
    save_project(project)
    return {"project": project, "artifacts": artifact_urls(project)}


@app.post("/api/projects/{project_id}/segments/{segment_id}/merge-next")
async def merge_segment_with_next(project_id: str, segment_id: int):
    project = _load_or_404(project_id)
    index = next((idx for idx, segment in enumerate(project.segments) if segment.id == segment_id), None)
    if index is None or index + 1 >= len(project.segments):
        raise HTTPException(status_code=404, detail="next segment not found")
    first = project.segments[index]
    second = project.segments[index + 1]
    if first.locked or second.locked:
        raise HTTPException(status_code=400, detail="locked segment cannot be merged")
    target_lang = project.target_lang if project.target_lang != "none" else project.source_lang
    merged_source = " ".join(part.strip() for part in [first.source_text, second.source_text] if part.strip())
    merged_translated = " ".join(part.strip() for part in [first.translated_text or "", second.translated_text or ""] if part.strip()) or None
    merged_display = " ".join(part.strip() for part in [first.display_text, second.display_text] if part.strip())
    first.end_ms = second.end_ms
    first.source_text = merged_source
    first.translated_text = merged_translated
    first.display_text = wrap_display_text(merged_translated or merged_display or merged_source, target_lang)
    del project.segments[index + 1]
    _renumber_segments(project)
    project.status = "edited"
    apply_quality(project)
    save_project(project)
    return {"project": project, "artifacts": artifact_urls(project)}


@app.post("/api/projects/{project_id}/render")
async def render_project(project_id: str, request: RenderRequest):
    project = _load_or_404(project_id)
    if not project.segments:
        raise HTTPException(status_code=400, detail="先に文字起こしを実行してください。出力する字幕がまだありません。")
    if request.style:
        project.style = request.style
    outputs = set(request.outputs)
    if "ass" in outputs:
        try:
            write_ass(project)
        except RenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "srt" in outputs:
        try:
            write_srt(project)
        except RenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "vtt" in outputs:
        try:
            write_vtt(project)
        except RenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "bilingual_ass" in outputs:
        try:
            write_bilingual_ass(project)
        except RenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "mp4" not in outputs and "preview_mp4" not in outputs:
        project.status = "rendered"
        apply_quality(project)
        save_project(project)
        return {"project": project, "artifacts": artifact_urls(project)}

    async def task(context: JobContext):
        try:
            job_project = load_project(project_id)
            if request.style:
                job_project.style = request.style
            await context.update(5, "Writing subtitles")
            write_ass(job_project)
            write_srt(job_project)
            if "vtt" in outputs:
                write_vtt(job_project)
            if "bilingual_ass" in outputs:
                write_bilingual_ass(job_project)
            await context.update(20, "Burning subtitles")
            if "preview_mp4" in outputs:
                await asyncio.to_thread(burn_preview_mp4, job_project, context.check_cancel)
            if "mp4" in outputs:
                await asyncio.to_thread(burn_mp4, job_project, context.check_cancel)
            job_project = load_project(project_id)
            job_project.status = "rendered"
            save_project(job_project)
            await context.update(100, "Render complete")
            return {"project": job_project.model_dump(), "artifacts": artifact_urls(job_project)}
        except Exception:
            _mark_failed(project_id)
            raise

    job = await job_manager.submit("render", project_id, task)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    if job_id not in job_manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return await job_manager.cancel(job_id)


@app.websocket("/ws/jobs/{job_id}")
async def job_websocket(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    if job_id not in job_manager.jobs:
        await websocket.send_json({"status": "failed", "error": "job not found"})
        await websocket.close()
        return
    queue = await job_manager.subscribe(job_id)
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
            if payload.get("status") in {"succeeded", "failed", "canceled"}:
                await websocket.close()
                return
    except WebSocketDisconnect:
        pass
    finally:
        job_manager.unsubscribe(job_id, queue)


def _load_or_404(project_id: str) -> CaptionProject:
    try:
        return load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


def _mark_failed(project_id: str) -> None:
    try:
        project = load_project(project_id)
        project.status = "failed"
        project.generation_status = {"stage": "failed", "message": "処理に失敗しました"}
        save_project(project)
    except Exception:
        pass


def _renumber_segments(project: CaptionProject) -> None:
    for idx, segment in enumerate(project.segments, 1):
        segment.id = idx


def normalize_language(value: str) -> str:
    return (value or "").lower().split("-")[0]


def translation_decision(source_lang: str, target_lang: str, translate_mode: str = "auto") -> dict:
    target = normalize_language(target_lang)
    source = normalize_language(source_lang)
    if translate_mode == "off" or target == "none":
        return {"translate": False, "reason": "翻訳設定が「なし」のため翻訳をスキップしました", "source": source, "target": target}
    if source and source != "auto" and source == target:
        return {"translate": False, "reason": f"入力言語が{source}のため翻訳をスキップしました", "source": source, "target": target}
    return {"translate": True, "reason": f"{source or 'auto'} から {target} へ翻訳します", "source": source, "target": target}


def _generation_complete_message(project: CaptionProject, warning_count: int) -> str:
    summary = project.translation_summary or {}
    translated = int(summary.get("translated") or 0)
    total = len(project.segments)
    return f"字幕作成完了: 文字起こし {total}件 / 翻訳 {translated}件 / 警告 {warning_count}件"
