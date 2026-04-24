import shutil
import subprocess

import pytest

from app.models import CaptionProject, CaptionSegment, VideoMetadata
from app.services.render import burn_mp4


def test_burn_mp4_uses_available_subtitle_filter(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    video = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    import app.services.storage as storage

    storage.PROJECTS_DIR = tmp_path / "projects"
    project = CaptionProject(
        id="burntest",
        video_path=str(video),
        video_name=video.name,
        metadata=VideoMetadata(width=320, height=180, duration_ms=1000, has_audio=True, has_video=True),
        segments=[CaptionSegment(id=1, start_ms=0, end_ms=900, source_text="hello", display_text="hello")],
    )
    output = burn_mp4(project)
    assert output.exists()
    assert output.stat().st_size > 0
