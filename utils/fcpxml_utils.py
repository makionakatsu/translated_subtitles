import xml.dom.minidom
from xml.etree.ElementTree import Element, SubElement, ElementTree, Comment
import io
import datetime # Import datetime module
import ffmpeg # Import ffmpeg for probing
import logging
import math

logger = logging.getLogger(__name__)

# --- Helper to format time for FCPXML (fractional seconds) ---
def to_fractional_time(seconds, frame_rate=24.0):
    """Converts seconds to FCPXML fractional time format 'frames/fpss'."""
    if seconds is None: return "0/1s"
    # Ensure frame_rate is float for division
    frame_rate = float(frame_rate) if frame_rate else 24.0
    if frame_rate <= 0: frame_rate = 24.0 # Avoid division by zero
    
    # Calculate total frames, ensuring non-negative result
    total_frames = max(0, round(seconds * frame_rate))
    
    # Format as fraction, ensuring integer frame rate in denominator if possible
    if frame_rate.is_integer():
        return f"{total_frames}/{int(frame_rate)}s"
    else:
        # Use a common denominator like 100 or 1000 for non-integer rates if needed,
        # but standard practice is often to just use the float rate.
        # For simplicity, we'll use the float rate directly here.
        # A more robust solution might involve finding common denominators.
        return f"{total_frames}/{frame_rate:.2f}s" # Format float rate

# --- generate_fcpxml: Whisperセグメントを元に Final Cut Pro 用 FCPXML 文字列を生成 ---
# Modified signature to accept font_size (defaulting to 65 now)
def generate_fcpxml(segments, video_path=None, font_size=65): 
    """
    Generates FCPXML content string from Whisper segments.
    Optionally probes video_path for accurate duration and frame rate.

    Args:
        segments: Iterable of Whisper segment objects (or dicts) with 'start', 'end', 'text'.
        video_path (str, optional): Path to the source video file for probing. Defaults to None.
        font_size (int, optional): Font size to apply to the titles. Defaults to 65.

    Returns:
        str: The generated FCPXML content as a string, or None if generation fails.
    """
    if not segments:
        logger.warning("No subtitle segments provided for FCPXML generation.")
        return None

    # --- Default video properties ---
    width = 1920
    height = 1080
    frame_rate = 24.0 # Default frame rate
    sequence_duration_s = 60.0 # Default duration in seconds

    # --- Probe video for accurate properties if path is provided ---
    if video_path:
        try:
            logger.info(f"Probing video for FCPXML metadata: {video_path}")
            probe = ffmpeg.probe(video_path)
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            
            if video_stream:
                width = int(video_stream.get('width', width))
                height = int(video_stream.get('height', height))
                
                # Get frame rate (may be fraction like '30000/1001')
                r_frame_rate = video_stream.get('r_frame_rate')
                if r_frame_rate and '/' in r_frame_rate:
                    num, den = map(float, r_frame_rate.split('/'))
                    if den != 0:
                        frame_rate = num / den
                elif 'avg_frame_rate' in video_stream and '/' in video_stream['avg_frame_rate']:
                     num, den = map(float, video_stream['avg_frame_rate'].split('/'))
                     if den != 0:
                         frame_rate = num / den

                # Get duration
                duration_str = video_stream.get('duration')
                if duration_str:
                    try:
                        sequence_duration_s = float(duration_str)
                    except ValueError:
                         logger.warning(f"Could not parse video duration '{duration_str}'. Using default.")
                elif probe.get('format', {}).get('duration'):
                     try:
                         sequence_duration_s = float(probe['format']['duration'])
                     except ValueError:
                         logger.warning(f"Could not parse format duration '{probe['format']['duration']}'. Using default.")

                logger.info(f"Probed video: {width}x{height}, Rate: {frame_rate:.2f} fps, Duration: {sequence_duration_s:.2f}s")
            else:
                logger.warning(f"No video stream found in probe for {video_path}. Using default metadata.")
        except Exception as probe_err:
            logger.warning(f"ffmpeg.probe failed for {video_path}: {probe_err}. Using default metadata.")

    # Ensure sequence duration covers the last subtitle
    last_segment_end = 0
    try:
        # Find the end time of the last segment
        valid_segments = [s for s in segments if hasattr(s, 'end') or (isinstance(s, dict) and 'end' in s)]
        if valid_segments:
            last_segment_end = max(getattr(s, 'end', s.get('end', 0)) for s in valid_segments)
        sequence_duration_s = max(sequence_duration_s, math.ceil(last_segment_end) + 1) # Add buffer
    except Exception as e:
        logger.warning(f"Could not determine last segment end time: {e}. Using probed/default duration.")

    sequence_duration_frac = to_fractional_time(sequence_duration_s, frame_rate)
    format_id = "r1"
    effect_id = "r2" # Basic Title effect

    # --- Build FCPXML Structure ---
    fcpxml = Element('fcpxml', version="1.13")
    
    # Add comment about generation
    fcpxml.append(Comment(f" Generated by Subtitle Tool on {datetime.now().isoformat()} "))

    resources = SubElement(fcpxml, 'resources')
    # Define format based on probed/default video properties
    SubElement(resources, 'format', id=format_id, name=f"FFVideoFormat{height}p{frame_rate:.2f}",
               frameDuration=f"{int(100000/frame_rate)}/100000s" if frame_rate else "100/2400s", # Approximate frame duration
               width=str(width), height=str(height))
    # Define the Basic Title effect (adjust uid if necessary for specific FCP versions)
    SubElement(resources, 'effect', id=effect_id, name="Basic Title",
               uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti")

    library = SubElement(fcpxml, 'library')
    event = SubElement(library, 'event', name="Subtitle Import")
    project = SubElement(event, 'project', name="Generated Subtitles Project")
    sequence = SubElement(project, 'sequence', duration=sequence_duration_frac, format=format_id, tcStart="0s", tcFormat="NDF") # NDF = Non-Drop Frame
    spine = SubElement(sequence, 'spine')

    # Create a gap that covers the entire sequence duration
    gap = SubElement(spine, 'gap', name="Base Gap", offset="0s", duration=sequence_duration_frac, start="0s")

    # Add titles (subtitles) within the gap
    title_count = 0
    for segment in segments:
        try:
            # Extract data (handle both objects and dicts)
            if hasattr(segment, 'start') and hasattr(segment, 'end') and hasattr(segment, 'text'):
                start_s = segment.start
                end_s = segment.end
                text = segment.text.strip()
            elif isinstance(segment, dict) and 'start' in segment and 'end' in segment and 'text' in segment:
                start_s = segment['start']
                end_s = segment['end']
                text = segment['text'].strip()
            else:
                logger.warning(f"Skipping invalid segment structure for FCPXML: {segment}")
                continue

            if start_s is None or end_s is None or text is None or start_s >= end_s:
                 logger.warning(f"Skipping segment with invalid time or text: Start={start_s}, End={end_s}, Text='{text}'")
                 continue

            duration_s = end_s - start_s
            offset_frac = to_fractional_time(start_s, frame_rate)
            duration_frac = to_fractional_time(duration_s, frame_rate)
            
            # Ensure minimum duration for visibility in FCP
            if duration_s < (1 / frame_rate):
                 duration_frac = to_fractional_time(1 / frame_rate, frame_rate) # Min 1 frame duration

            # Create the title element
            title = SubElement(gap, 'title', name=text[:30], lane="1", # Use first 30 chars for name
                               offset=offset_frac, ref=effect_id, duration=duration_frac)
            
            # Add text style definition (Basic Title uses this structure)
            text_elem = SubElement(title, 'text')
            text_style = SubElement(text_elem, 'text-style', ref=f"ts{title_count+1}") # Unique ref for style
            text_style.text = text # Set the actual subtitle text here

            # Define the text style properties (can be customized)
            SubElement(title, 'text-style-def', id=f"ts{title_count+1}") # Matches ref above
            # Add parameters for Basic Title (font, size, position, etc.) - Example:
            SubElement(title, 'param', name="Position", key="9999/999166631/999166633/1/100/101", value="0 -450") # Center bottom-ish
            SubElement(title, 'param', name="Alignment", key="9999/999166631/999166633/1/100/100", value="1") # Center align = 1
            SubElement(title, 'param', name="Font", key="9999/999166631/999166633/5/100/105", value="Helvetica")
            # Use the provided font_size, ensuring it's an integer string
            final_font_size_str = str(max(10, int(font_size))) # Ensure minimum size 10
            SubElement(title, 'param', name="Size", key="9999/999166631/999166633/5/100/103", value=final_font_size_str)

            title_count += 1
        except Exception as e:
            logger.error(f"Error processing segment for FCPXML: {segment}. Error: {e}")
            continue # Skip segment on error

    if title_count == 0:
        logger.warning("No valid titles were added to the FCPXML spine.")
        # Optionally return None or an empty structure
        # return None 

    # --- Serialize XML ---
    try:
        # Use io.StringIO to write XML to a string
        xml_buffer = io.StringIO()
        tree = ElementTree(fcpxml)
        tree.write(xml_buffer, encoding='unicode', xml_declaration=True)
        xml_str = xml_buffer.getvalue()
        
        # Use minidom for pretty printing (optional, adds indentation)
        # parsed_xml = xml.dom.minidom.parseString(xml_str)
        # pretty_xml_str = parsed_xml.toprettyxml(indent="  ", encoding="utf-8").decode('utf-8')
        # return pretty_xml_str
        
        return xml_str # Return non-prettified XML string

    except Exception as e:
        logger.error(f"Error serializing FCPXML: {e}")
        return None
