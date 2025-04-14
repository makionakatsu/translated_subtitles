# utils/style_loader.py
import json
import os
import logging # Import logging

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- load_styles: styles.json ファイルを読み込んで字幕スタイル設定を辞書として返す関数 ---
def load_styles(path="styles.json"):
    """Loads style definitions from a JSON file."""
    if not os.path.exists(path):
        logger.warning(f"Style file not found at {path}. Returning empty styles.")
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            styles = json.load(f)
            logger.info(f"Successfully loaded styles from {path}")
            return styles
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading styles from {path}: {e}")
        return {}
