"""Segment / Word / Job pydantic models shared across services and the editor UI."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["download", "convert", "transcribe", "translate", "write", "burn"]


class Word(BaseModel):
    start: float
    end: float
    text: str
    prob: float = 1.0


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    original_text: str | None = None
    words: list[Word] = Field(default_factory=list)
    speaker: str | None = None
    locked: bool = False
    avg_logprob: float | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobProgress(BaseModel):
    stage: Stage
    pct: float
    msg: str
    eta_sec: float | None = None
