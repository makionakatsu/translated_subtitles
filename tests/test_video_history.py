"""End-to-end checks for video history detection and ignore patterns."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_video_history.py"


class VideoHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", *args), cwd=self.repo, text=True, capture_output=True, check=True
        )

    def add_commit(self, path: str, content: str = "sample") -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self.git("add", "-f", path)
        self.git("commit", "-qm", f"add {path}")

    def check_history(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, str(CHECKER)), cwd=self.repo, text=True, capture_output=True
        )

    def test_clean_history_and_typescript_are_allowed(self) -> None:
        self.add_commit("apps/web/lib/player.ts")
        self.assertEqual(self.check_history().returncode, 0)

    def test_video_in_head_is_rejected(self) -> None:
        self.add_commit("clip.mp4")
        self.assertEqual(self.check_history().returncode, 1)

    def test_nested_mixed_case_video_is_rejected(self) -> None:
        self.add_commit("nested/deep/clip.Mp4")
        result = self.check_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn("clip.Mp4", result.stderr)

    def test_video_added_then_deleted_still_fails(self) -> None:
        self.add_commit("nested/clip.webm")
        (self.repo / "nested/clip.webm").unlink()
        self.git("add", "-u")
        self.git("commit", "-qm", "remove video")
        self.assertEqual(self.check_history().returncode, 1)

    def test_gitignore_covers_video_suffixes_but_not_typescript(self) -> None:
        shutil.copy2(ROOT / ".gitignore", self.repo / ".gitignore")
        for suffix in ("mp4", "Mp4", "MOV", "mKv", "webm", "M2TS", "3Gp"):
            with self.subTest(suffix=suffix):
                self.git("check-ignore", "-q", f"nested/deep/clip.{suffix}")
        allowed = subprocess.run(
            ("git", "check-ignore", "-q", "apps/web/lib/player.ts"), cwd=self.repo
        )
        self.assertEqual(allowed.returncode, 1)


if __name__ == "__main__":
    unittest.main()
