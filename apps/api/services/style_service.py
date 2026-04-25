"""Style storage: bundled ``styles.json`` plus user-defined styles.

In Phase 0/1 we only read the bundled file. Phase 4 plumbs through SQLite
so the editor can persist user styles. The function shape is kept ready for
that extension (``load_styles()`` returns a merged dict).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STYLES_PATH = REPO_ROOT / "styles.json"

_CACHE: dict[str, dict[str, str]] | None = None


def load_styles(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Return the bundled styles dictionary (cached on first read)."""
    global _CACHE
    if _CACHE is not None and path is None:
        return dict(_CACHE)

    target = path or DEFAULT_STYLES_PATH
    if not target.exists():
        logger.warning("styles.json not found at %s; returning empty dict", target)
        return {}

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("styles.json must be a top-level object; got %s", type(data).__name__)
            return {}
        # styles.json may contain int values (e.g. "Outline": 3); coerce to str
        # so consumers (the FastAPI response model and the ASS writer) can rely
        # on a uniform contract.
        coerced: dict[str, dict[str, str]] = {
            name: {k: str(v) for k, v in (style or {}).items()}
            for name, style in data.items()
        }
        if path is None:
            _CACHE = coerced
        return dict(coerced)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse %s: %s", target, e)
        return {}


def reset_cache() -> None:
    """Used by tests."""
    global _CACHE
    _CACHE = None
