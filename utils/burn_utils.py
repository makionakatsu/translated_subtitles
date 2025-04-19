"""
Utility: burn_utils.py
----------------------
Contains helper to burn an external subtitle file into a video using ffmpeg.
"""

import subprocess
from pathlib import Path

class BurnError(RuntimeError):
    """Raised when ffmpeg burning fails."""

def burn_subtitles(
    video_path: Path,
    subtitle_path: Path,
    font_size: int = 24,
    out_dir: Path | str = "./burn_temp",
) -> Path:
    """
    Burn subtitles into a video file.

    Args:
        video_path: Path to the source video.
        subtitle_path: Path to the subtitle (SRT/ASS) file.
        font_size: ASS style Fontsize to apply.
        out_dir: Directory to write the burned video.

    Returns:
        Path of the burned MP4.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)

    output_path = out_dir / f"burn_{video_path.name}"

    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-vf",
        f"subtitles='{subtitle_path}':force_style='Fontsize={font_size}'",
        "-c:a",
        "copy",
        str(output_path),
        "-y",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise BurnError(e.stderr.decode(errors="ignore")) from e

    return output_path
