# utils/video_utils.py

import subprocess
import os
import logging
import ffmpeg

logger = logging.getLogger(__name__)

# --- convert_to_wav: 指定された動画/音声ファイルを wav フォーマット（mono, 16kHz）に変換する関数 ---
def convert_to_wav(input_path, output_path):
    """
    Converts the input media file to a WAV file format required by Whisper.
    (16kHz, mono, PCM 16-bit little-endian)

    Args:
        input_path (str): Path to the input media file.
        output_path (str): Path where the output WAV file will be saved.

    Returns:
        str: The path to the converted WAV file if successful, None otherwise.
    """
    logger.info(f"Converting '{input_path}' to WAV format at '{output_path}'...")
    try:
        # Ensure the output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        command = [
            "ffmpeg", "-i", input_path,
            "-vn",  # Disable video recording
            "-acodec", "pcm_s16le",  # Audio codec: PCM 16-bit little-endian
            "-ar", "16000",          # Audio sample rate: 16kHz
            "-ac", "1",              # Audio channels: mono
            output_path,
            "-y"                     # Overwrite output file if it exists
        ]
        
        # Execute ffmpeg command
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        
        logger.info(f"Successfully converted '{input_path}' to '{output_path}'")
        logger.debug(f"ffmpeg stdout:\n{result.stdout}")
        logger.debug(f"ffmpeg stderr:\n{result.stderr}")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg conversion failed for '{input_path}'.")
        logger.error(f"Command: {' '.join(e.cmd)}")
        logger.error(f"Return code: {e.returncode}")
        logger.error(f"Stderr:\n{e.stderr}")
        # Clean up potentially corrupted output file
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.info(f"Removed potentially corrupted output file: '{output_path}'")
            except OSError as remove_err:
                logger.error(f"Failed to remove corrupted output file '{output_path}': {remove_err}")
        return None
    except FileNotFoundError:
        logger.error("ffmpeg command not found. Please ensure ffmpeg is installed and in your system's PATH.")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during WAV conversion: {e}")
        # Clean up potentially corrupted output file
        if os.path.exists(output_path):
             try:
                os.remove(output_path)
                logger.info(f"Removed potentially corrupted output file: '{output_path}'")
             except OSError as remove_err:
                logger.error(f"Failed to remove corrupted output file '{output_path}': {remove_err}")
        return None

def get_video_resolution(input_path: str) -> tuple[int, int]:
    """
    Retrieves the width and height of the video file at input_path using ffmpeg.probe.

    Args:
        input_path (str): Path to the video file.

    Returns:
        tuple[int, int]: (width, height) in pixels, or (0, 0) on failure.
    """
    try:
        info = ffmpeg.probe(input_path)
        video_stream = next(
            (s for s in info["streams"] if s.get("codec_type") == "video"),
            None,
        )
        if video_stream:
            width = video_stream.get("width", 0)
            height = video_stream.get("height", 0)
            return width, height
        logger.error(f"No video stream found in '{input_path}'")
    except Exception as e:
        logger.error(f"Failed to probe video resolution for '{input_path}': {e}")
    return 0, 0
