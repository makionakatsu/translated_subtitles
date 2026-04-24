import textwrap
import logging # Import logging
# Assuming style_loader might be needed here eventually, but not for current functions
# from .style_loader import load_styles 

# Utility function to auto-wrap text for ASS subtitles
def auto_wrap_text(text, max_chars_per_line=40, max_lines=2):
    """
    Inserts \N into text to wrap lines at natural breakpoints.
    Prioritizes full-width punctuation and spaces.
    """
    import re

    # Clean text
    clean_text = text.strip()

    # Break into chunks using punctuation as soft break hints
    # This splits on Japanese/English punctuation and spaces
    parts = re.split(r'([。、！？,.!? 　])', clean_text)

    lines = []
    current_line = ''
    for part in parts:
        # Try to append the next part
        if len(current_line + part) <= max_chars_per_line:
            current_line += part
        else:
            lines.append(current_line.strip())
            current_line = part
            # Stop if max_lines reached
            if len(lines) >= max_lines:
                break

    if current_line and len(lines) < max_lines:
        lines.append(current_line.strip())

    return '\\N'.join(lines)

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- format_ass_time: 秒数を ASS 形式の h:mm:ss.cc タイムスタンプに変換する関数 ---
def format_ass_time(t):
    """Converts seconds to ASS time format h:mm:ss.cc"""
    if t is None:
        return "0:00:00.00"
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    centiseconds = int((t % 1) * 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

# --- generate_ass_header: ASSファイルのヘッダーとスタイル情報を生成する ---
# Modified signature to accept font_size (which now comes from main4.py's UI)
def generate_ass_header(width, height, styles_data, chosen_style_name="Default", show_bg=False, font_size=65): # Default to 65 if not passed
    """Generates the [Script Info] and [V4+ Styles] sections for an ASS file."""
    
    # Ensure the chosen style exists in the loaded styles data
    # styles_data is expected to be a dict loaded from styles.json in the main script
    if chosen_style_name not in styles_data:
        logger.warning(f"Style '{chosen_style_name}' not found in styles data. Falling back to 'Default'.")
        # Fallback to 'Default' if chosen style not found
        chosen_style = styles_data.get("Default", {})
        if not chosen_style: # If 'Default' also doesn't exist, create a minimal default
             logger.warning("'Default' style not found. Creating a minimal default style.")
             chosen_style = {
                 "Fontname": "Meiryo", "Fontsize": "20", "PrimaryColour": "&H00FFFFFF",
                 "SecondaryColour": "&H000000FF", "OutlineColour": "&H00000000", "BackColour": "&H80000000",
                 "Bold": "0", "Italic": "0", "Underline": "0", "StrikeOut": "0",
                 "ScaleX": "100", "ScaleY": "100", "Spacing": "0", "Angle": "0",
                 "BorderStyle": "1", "Outline": "1", "Shadow": "0",
                 "Alignment": "2", "MarginL": "10", "MarginR": "10", "MarginV": "10", "Encoding": "128"
             }
             chosen_style_name = "Default" # Ensure name matches
    else:
        chosen_style = styles_data[chosen_style_name]

    # Determine background color based on show_bg flag
    if show_bg:
        # Get the RGB part of the BackColour from the style, default to black (000000)
        style_back_color = chosen_style.get("BackColour", "&H80000000") 
        # Extract BBGGRR part (last 6 hex digits)
        if len(style_back_color) == 10 and style_back_color.startswith("&H"):
             rgb_part = style_back_color[4:]
        else: # Use default black if format is wrong
             rgb_part = "000000" 
        # Set Alpha to 00 (opaque)
        back_color = f"&H00{rgb_part}" 
        logger.info(f"Setting opaque background color: {back_color}")
    else:
        # Set fully transparent background
        back_color = "&HFF000000" # Alpha FF for transparent

    # Use the provided font_size directly, ensuring it's an integer and has a minimum value
    final_font_size = max(10, int(font_size)) 
    logger.info(f"Using font size for ASS style: {final_font_size}")
    
    # Calculate vertical margin based on video height
    margin_v = int(height * 0.05) # Vertical margin (e.g., 5% of height)
    # Calculate horizontal margins as 5% of width
    margin_lr = int(width * 0.05)

    # Determine BorderStyle based on show_bg flag
    border_style = '3' if show_bg else chosen_style.get('BorderStyle', '1')

    # Construct the Style line using values from the chosen style or defaults
    # Use .get() with defaults for robustness
    style_line = (
        f"Style: {chosen_style_name},"
        f"{chosen_style.get('Fontname', 'Arial')},"
        f"{final_font_size}," # Use the determined font size
        f"{chosen_style.get('PrimaryColour', '&H00FFFFFF')},"
        f"{chosen_style.get('SecondaryColour', '&H000000FF')},"
        f"{chosen_style.get('OutlineColour', '&H00000000')},"
        f"{back_color}," # Use calculated back_color
        f"{chosen_style.get('Bold', '0')},"
        f"{chosen_style.get('Italic', '0')},"
        f"{chosen_style.get('Underline', '0')},"
        f"{chosen_style.get('StrikeOut', '0')},"
        f"{chosen_style.get('ScaleX', '100')},"
        f"{chosen_style.get('ScaleY', '100')},"
        f"{chosen_style.get('Spacing', '0')},"
        f"{chosen_style.get('Angle', '0')},"
        f"{border_style}," # Use calculated BorderStyle
        f"{chosen_style.get('Outline', '1')},"
        f"{chosen_style.get('Shadow', '0')},"
        f"{chosen_style.get('Alignment', '2')},"
        f"{margin_lr},"
        f"{margin_lr},"
        f"{margin_v}," # Use calculated margin_v
        f"{chosen_style.get('Encoding', '1')}"
    )
    # --- Debug Log ---
    logger.info(f"[ASS Header Debug] Generating header with: width={width}, height={height}")
    logger.info(f"[ASS Header Debug] Chosen Style: {chosen_style_name}")
    logger.info(f"[ASS Header Debug] Generated Style Line: {style_line}")
    # --- End Debug Log ---

    # Basic Script Info section
    header = f"""[Script Info]
Title: Generated by Subtitle Tool
ScriptType: v4.00+
WrapStyle: 1
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # NOTE: When writing this header to file, use encoding="utf-8-sig" to avoid Japanese text garbling
    return header

# --- generate_ass_dialogue: WhisperセグメントからASSダイアログ行を生成する ---
# Updated signature to accept styles_data to retrieve margins
def generate_ass_dialogue(segments, styles_data, style_name="Default", width=1280, font_size=65, max_lines=2):
    """
    Generates ASS Dialogue lines from Whisper segments.

    Args:
        segments: Iterable of Whisper segment objects (or dicts) with 'start', 'end', 'text'.
        style_name (str): The ASS style name to apply.
        width (int): The width of the video in pixels.
        font_size (int): The font size used for the subtitles.
        max_lines (int): The maximum number of lines per subtitle entry.

    Returns:
        str: The generated ASS dialogue lines as a string.
    """
    dialogue_lines = []
    # Ensure segments is iterable and contains expected structure
    if not hasattr(segments, '__iter__'):
        logger.error("Segments data is not iterable for ASS generation.")
        return "" # Return empty string if segments is not valid

    for segment in segments:
        try:
            # Check if segment is an object with attributes or a dict
            if hasattr(segment, 'start') and hasattr(segment, 'end') and hasattr(segment, 'text'):
                start_time = format_ass_time(segment.start)
                end_time = format_ass_time(segment.end)
                text = segment.text
            elif isinstance(segment, dict) and 'start' in segment and 'end' in segment and 'text' in segment:
                start_time = format_ass_time(segment['start'])
                end_time = format_ass_time(segment['end'])
                text = segment['text']
            else:
                logger.warning(f"Skipping invalid segment structure for ASS: {segment}")
                continue # Skip this segment if structure is wrong

            # --- Text Preparation for ASS ---
            # Rely on ASS WrapStyle for automatic wrapping; do not insert forced line breaks.
            formatted_text = text.strip().replace('\n', ' ')

            # --- Get Margins from Style ---
            # Find the chosen style in styles_data, fallback to Default or empty dict
            chosen_style = styles_data.get(style_name, styles_data.get("Default", {}))
            # Get margin values, defaulting to 10 if not found in style
            margin_l = chosen_style.get('MarginL', '10')
            margin_r = chosen_style.get('MarginR', '10')
            # Calculate MarginV based on height (as done in header) or get from style if defined
            margin_v_style = chosen_style.get('MarginV')
            if margin_v_style:
                 margin_v = margin_v_style
            else:
                 # Recalculate if not in style (using height passed to function, default 720 if not passed?)
                 # Need video height here. Let's assume header calculation is sufficient and use default 10 if not in style.
                 # Or better, ensure MarginV is always calculated/retrieved in header and passed?
                 # For now, let's use the style's MarginV if present, else default 10.
                 margin_v = chosen_style.get('MarginV', '10') # Defaulting to 10 if not in style

            # Create the dialogue line with explicit margins set to 0 (to use style defaults)
            # {\q2} tag removed to rely solely on WrapStyle: 0 and style margins for wrapping.
            # Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            dialogue = f"Dialogue: 0,{start_time},{end_time},{style_name},,,,,,{formatted_text}\n"
            dialogue_lines.append(dialogue)
        except Exception as e:
            logger.error(f"Error processing segment for ASS: {segment}. Error: {e}")
            # Optionally skip the segment or add placeholder text
            continue
            
    return "".join(dialogue_lines)
