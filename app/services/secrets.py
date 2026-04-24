from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional


SERVICE = "Local Caption MVP"
ACCOUNT = "gemini_api_key"
SECRET_DIR = Path(os.getenv("LOCAL_CAPTION_CONFIG_DIR", Path.home() / ".local_caption_mvp"))
SECRET_FILE = SECRET_DIR / "secrets.json"


def load_gemini_api_key() -> Optional[str]:
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        return env_key.strip()
    key = _load_from_keychain()
    if key:
        return key
    return _load_from_file()


def save_gemini_api_key(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("Gemini API key is empty")
    if _keychain_available():
        try:
            _save_to_keychain(key)
            return "macOS Keychain"
        except Exception:
            pass
    _save_to_file(key)
    return str(SECRET_FILE)


def delete_gemini_api_key() -> None:
    _delete_from_keychain()
    if SECRET_FILE.exists():
        SECRET_FILE.unlink()


def gemini_api_key_status() -> dict:
    if os.getenv("GEMINI_API_KEY"):
        return {"configured": True, "source": "environment"}
    if _load_from_keychain():
        return {"configured": True, "source": "macOS Keychain"}
    if _load_from_file():
        return {"configured": True, "source": str(SECRET_FILE)}
    return {"configured": False, "source": "missing"}


def _keychain_available() -> bool:
    return platform.system() == "Darwin" and shutil.which("security") is not None


def _load_from_keychain() -> Optional[str]:
    if not _keychain_available():
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _save_to_keychain(api_key: str) -> None:
    result = subprocess.run(
        ["security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w", api_key, "-U"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to save Gemini API key")


def _delete_from_keychain() -> None:
    if not _keychain_available():
        return
    subprocess.run(
        ["security", "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
        capture_output=True,
        text=True,
        check=False,
    )


def _load_from_file() -> Optional[str]:
    if not SECRET_FILE.exists():
        return None
    try:
        data = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    key = data.get("gemini_api_key") if isinstance(data, dict) else None
    return key.strip() if isinstance(key, str) and key.strip() else None


def _save_to_file(api_key: str) -> None:
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_DIR.chmod(stat.S_IRWXU)
    tmp_path = SECRET_FILE.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump({"gemini_api_key": api_key}, handle)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp_path, SECRET_FILE)
    SECRET_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
