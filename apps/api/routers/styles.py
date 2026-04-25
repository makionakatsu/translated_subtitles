"""Styles router: read-only in Phase 1; user-style CRUD lands in Phase 4."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import style_service

router = APIRouter(prefix="/api/styles", tags=["styles"])


@router.get("")
async def list_styles() -> dict[str, dict[str, str]]:
    return style_service.load_styles()
