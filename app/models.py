from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VideoMetadata(BaseModel):
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_video: bool = False
    format_name: str = ""


class StylePreset(BaseModel):
    name: str = "Readable"
    font_family: str = "Arial"
    font_size_mode: str = "auto"
    font_size: int = 56
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline_px: int = 3
    shadow_px: int = 1
    background_enabled: bool = False
    margin_v_ratio: float = 0.08
    max_lines: int = 2


class CaptionSegment(BaseModel):
    id: int
    start_ms: int
    end_ms: int
    source_text: str = ""
    translated_text: Optional[str] = None
    display_text: str = ""
    locked: bool = False
    warnings: List[str] = Field(default_factory=list)


class CaptionProject(BaseModel):
    id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    video_path: str
    video_name: str
    metadata: VideoMetadata = Field(default_factory=VideoMetadata)
    source_lang: str = "auto"
    target_lang: str = "none"
    style: StylePreset = Field(default_factory=StylePreset)
    segments: List[CaptionSegment] = Field(default_factory=list)
    status: str = "created"
    artifacts: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {
            "ass_path": None,
            "srt_path": None,
            "vtt_path": None,
            "bilingual_ass_path": None,
            "burned_mp4_path": None,
            "preview_mp4_path": None,
        }
    )
    translation_engine: str = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    translation_batches: List[Dict[str, Any]] = Field(default_factory=list)
    translation_cost_estimate: Optional[Dict[str, Any]] = None
    translation_summary: Dict[str, Any] = Field(default_factory=dict)
    last_translation_error: Optional[str] = None
    generation_plan: Dict[str, Any] = Field(default_factory=dict)
    generation_status: Dict[str, Any] = Field(default_factory=dict)
    asr_engine: str = "auto"
    asr_model: str = ""
    asr_device: str = ""
    asr_duration_sec: Optional[float] = None
    stage_timings: Dict[str, float] = Field(default_factory=dict)


class SegmentPatch(BaseModel):
    id: int
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    display_text: Optional[str] = None
    locked: Optional[bool] = None


class SegmentSplitRequest(BaseModel):
    at_ms: Optional[int] = None


class TranscribeRequest(BaseModel):
    preset: str = "fast"
    source_lang: str = "auto"
    asr_engine: str = "auto"


class TranslateRequest(BaseModel):
    target_lang: str
    api_key: Optional[str] = None
    engine: str = "gemini"


class GenerateRequest(BaseModel):
    preset: str = "fast"
    source_lang: str = "auto"
    target_lang: str = "ja"
    asr_engine: str = "auto"
    translate_mode: str = "auto"
    api_key: Optional[str] = None


class GeminiKeyRequest(BaseModel):
    api_key: str


class RenderRequest(BaseModel):
    outputs: List[str] = Field(default_factory=lambda: ["ass", "srt"])
    style: Optional[StylePreset] = None


class JobState(BaseModel):
    id: str
    project_id: Optional[str] = None
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "queued"
    stage: str = "queued"
    stage_label: str = "待機中"
    stage_progress: float = 0.0
    current_item: Optional[int] = None
    total_items: Optional[int] = None
    eta_sec: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    cancel_requested: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_sec: Optional[float] = None
    stage_timings: Dict[str, float] = Field(default_factory=dict)


class PreflightCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class PreflightResponse(BaseModel):
    checks: List[PreflightCheck]
    gemini_model: str
