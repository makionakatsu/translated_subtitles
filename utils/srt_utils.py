# utils/srt_utils.py

import re
from datetime import timedelta
import textwrap
import logging # Import logging

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- format_srt_time: 秒数を SRT 形式の hh:mm:ss,ms タイムスタンプに変換する関数 ---
def format_srt_time(t):
    """Converts seconds to SRT time format hh:mm:ss,ms"""
    if t is None:
        return "00:00:00,000"
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    milliseconds = int((t % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# --- srt_time_to_seconds: SRT形式の字幕時間表記を秒数に変換する関数 ---
def srt_time_to_seconds(srt_time: str) -> float:
    """Converts SRT time format hh:mm:ss,ms to seconds"""
    try:
        h, m, s_ms = srt_time.split(':')
        s, ms = s_ms.split(',')
        td = timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))
        return td.total_seconds()
    except ValueError:
        # Handle potential format errors gracefully
        logger.warning(f"Could not parse SRT time format: {srt_time}")
        return 0.0

# --- parse_srt: SRTファイルを解析して各字幕エントリを辞書のリストとして返す関数 ---
def parse_srt(filepath: str):
    """Parses an SRT file and returns a list of subtitle dictionaries."""
    subtitles = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        logger.error(f"SRT file not found at {filepath}")
        return []
    except Exception as e:
        logger.error(f"Error reading SRT file {filepath}: {e}")
        return []

    # Use regex to find blocks, more robust against extra newlines
    blocks = re.findall(r'(\d+)\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*([\s\S]*?)(?=\n\n\d+\s|\Z)', content)

    for block in blocks:
        try:
            index = int(block[0])
            start_str = block[1]
            end_str = block[2]
            text = block[3].strip()
            
            start = srt_time_to_seconds(start_str)
            end = srt_time_to_seconds(end_str)

            subtitles.append({'index': index, 'start': start, 'end': end, 'text': text})
        except Exception as e:
            logger.warning(f"Could not parse SRT block: {block}. Error: {e}")
            continue # Skip malformed blocks

    return subtitles

# --- generate_srt_content: WhisperセグメントからSRTファイルの内容を生成する ---
# Updated signature to accept width and font_size
def generate_srt_content(segments, width=1280, font_size=65, max_lines=2):
    """
    Generates SRT file content string from Whisper segments, dynamically calculating line length.

    Args:
        segments: Iterable of Whisper segment objects (or dicts) with 'start', 'end', 'text'.
        width (int): The width of the video in pixels (used for line length calculation).
        font_size (int): The font size used for the subtitles (used for line length calculation).
        max_lines (int): The maximum number of lines per subtitle entry.

    Returns:
        str: The generated SRT content as a string.
    """
    srt_blocks = []
    # Ensure segments is iterable and contains expected structure
    if not hasattr(segments, '__iter__'):
        logger.error("Segments data is not iterable for SRT generation.")
        return "" # Return empty string if segments is not valid

    for i, segment in enumerate(segments, 1):
        try:
             # Check if segment is an object with attributes or a dict
            if hasattr(segment, 'start') and hasattr(segment, 'end') and hasattr(segment, 'text'):
                start_time_str = format_srt_time(segment.start)
                end_time_str = format_srt_time(segment.end)
                text = segment.text
            elif isinstance(segment, dict) and 'start' in segment and 'end' in segment and 'text' in segment:
                start_time_str = format_srt_time(segment['start'])
                end_time_str = format_srt_time(segment['end'])
                text = segment['text']
            else:
                logger.warning(f"Skipping invalid segment structure for SRT: {segment}")
                continue # Skip this segment

            # --- Dynamic Line Length Calculation ---
            # Heuristic: Assume average character width is roughly 0.6 * font_size
            # Aim for text to occupy ~80% of the video width. Adjust factors as needed.
            # Ensure font_size is not zero to avoid division error
            safe_font_size = max(1, font_size) # Use at least 1
            # Ensure width is positive
            safe_width = max(1, width)
            # Calculate approximate characters per line
            # Changed width factor from 0.8 to 0.7 to make lines shorter
            chars_per_line = int((safe_width * 0.7) / (safe_font_size * 0.6))
            # Set a minimum sensible length (e.g., 10 characters)
            dynamic_max_line_length = max(10, chars_per_line)
            logger.info(f"Calculated dynamic max_line_length for SRT: {dynamic_max_line_length} (width={width}, font_size={font_size})")

            # Basic text cleaning and wrapping using dynamic length
            cleaned_text = text.strip().replace('\n', ' ')
            wrapped_lines = textwrap.wrap(cleaned_text, width=dynamic_max_line_length, drop_whitespace=False, replace_whitespace=False)

            # Limit number of lines
            if len(wrapped_lines) > max_lines:
                wrapped_lines = wrapped_lines[:max_lines]

            formatted_text = "\n".join(wrapped_lines)

            # Create SRT block
            block = f"{i}\n{start_time_str} --> {end_time_str}\n{formatted_text}\n"
            srt_blocks.append(block)
        except Exception as e:
            logger.error(f"Error processing segment for SRT: {segment}. Error: {e}")
            continue

    return "\n".join(srt_blocks) # Join blocks with an extra newline
