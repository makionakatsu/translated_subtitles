# utils/style_loader.py
import json
import os
import logging # Import logging
logger = logging.getLogger(__name__)

# --- Preload styles once for performance ---
_CACHED_STYLES = {}
_styles_file = "styles.json"
if os.path.exists(_styles_file):
    try:
        with open(_styles_file, 'r', encoding='utf-8') as _f:
            _CACHED_STYLES = json.load(_f)
            logger.info(f"Successfully preloaded styles from {_styles_file}")
    except Exception as _e:
        logger.error(f"Failed to preload styles from {_styles_file}: {_e}")
else:
    logger.warning(f"Style file not found at import: {_styles_file}")

# --- load_styles: styles.json ファイルを読み込んで字幕スタイル設定を辞書として返す関数 ---
def load_styles(path="styles.json"):
    """
    Returns preloaded style definitions.
    """
    return _CACHED_STYLES.copy()
