"""Exercise the optional model cache lock without downloading model data."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version

import pytest

filelock = pytest.importorskip("filelock")
hub = pytest.importorskip("huggingface_hub.utils")


def test_model_cache_lock_uses_patched_filelock(tmp_path):
    assert tuple(map(int, version("filelock").split("."))) >= (4, 2, 1)
    path = tmp_path / "model.lock"

    def contend():
        with hub.WeakFileLock(path, timeout=0.1):
            raise AssertionError("second thread acquired an active lock")

    with hub.WeakFileLock(path, timeout=1):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(filelock.Timeout):
                pool.submit(contend).result(timeout=2)

    with hub.WeakFileLock(path, timeout=1):
        assert path.exists()
