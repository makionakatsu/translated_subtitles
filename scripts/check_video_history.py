"""Reject video files in any commit reachable from the checked-out revision."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

VIDEO_SUFFIXES = (
    b".mp4", b".mov", b".mkv", b".avi", b".webm", b".m4v",
    b".wmv", b".flv", b".mpeg", b".mpg", b".mts", b".m2ts",
    b".ogv", b".3gp", b".vob",
)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(("git", "-C", str(repo), *args))


def video_paths(repo: Path) -> list[tuple[str, bytes]]:
    """Inspect every commit tree, including files later deleted in the branch."""
    commits = git(repo, "rev-list", "HEAD").decode("ascii").splitlines()
    findings: list[tuple[str, bytes]] = []
    for commit in commits:
        for path in git(repo, "ls-tree", "-r", "-z", "--name-only", commit).split(b"\0"):
            if path and path.lower().endswith(VIDEO_SUFFIXES):
                findings.append((commit, path))
    return findings


def main() -> int:
    repo = Path.cwd()
    try:
        findings = video_paths(repo)
    except subprocess.CalledProcessError as error:
        print(f"Cannot inspect Git history: {error}", file=sys.stderr)
        return 2
    if findings:
        for commit, path in findings[:20]:
            print(f"video in {commit[:12]}: {os.fsdecode(path)!r}", file=sys.stderr)
        if len(findings) > 20:
            print(f"...and {len(findings) - 20} more commit/path occurrences", file=sys.stderr)
        return 1
    print("Video history check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
