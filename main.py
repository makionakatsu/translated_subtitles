import streamlit as st
from utils.whisper_utils import transcribe_with_faster_whisper
import ffmpeg
import os
from urllib.parse import urlparse
import yt_dlp
import json
from ffmpeg import Error
import requests
import textwrap
from datetime import datetime, timedelta
import glob
import re
from xml.etree.ElementTree import Element, SubElement, ElementTree
import xml.dom.minidom
# Import specific generation functions from utils
from utils.fcpxml_utils import generate_fcpxml
from utils.ass_utils import format_ass_time, generate_ass_header, generate_ass_dialogue
from utils.srt_utils import parse_srt, generate_srt_content
# Import the new translation functions
from utils.translate_utils import translate_text_deepl, translate_text_gemini
from dotenv import load_dotenv
from utils.style_loader import load_styles
from utils.video_utils import convert_to_wav
import queue
import subprocess
import logging
import time
from urllib.parse import urlparse
import shutil # Import shutil for copying files in Tab 2
from pathlib import Path # Add Pathlib import
import os # Import os module
import tempfile # Import tempfile module

# --- Helper function to determine output directory (Commented out - Tab 1 uses memory, Tab 2 uses tempfile) ---
# def get_output_dir():
#     """Determines the output directory as './generated_files' and creates it if needed."""
#     output_subdir = Path("./generated_files")
#     try:
#         # exist_ok=True でフォルダが既に存在してもエラーにならない
#         os.makedirs(output_subdir, exist_ok=True)
#         # Use logger if available, otherwise print
#         if 'logger' in globals():
#              logger.info(f"Ensured output directory exists: {output_subdir.resolve()}")
#         else:
#              print(f"Ensured output directory exists: {output_subdir.resolve()}")
#         return output_subdir
#     except OSError as e:
#         # Use logger if available, otherwise print error
#         if 'logger' in globals():
#             logger.error(f"Failed to create output directory '{output_subdir}': {e}")
#             logger.warning("Falling back to current directory for output.")
#         else:
#             print(f"ERROR: Failed to create output directory '{output_subdir}': {e}")
#             print("WARNING: Falling back to current directory for output.")
#         # Fallback to current directory if creation fails
#         return Path(".")

# --- Global Settings ---
MAX_CONCURRENT_TASKS = 5 # Placeholder, not currently used for sequential processing

# --- Logging Setup ---
logging.basicConfig(
    filename="process_log.log",
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Initialize session state ---
# if 'generated_files' not in st.session_state: # Old key, commented out
#     st.session_state['generated_files'] = []
if 'generated_subtitles_data' not in st.session_state:
    st.session_state['generated_subtitles_data'] = [] # New list for (video_path, filename, content_bytes)
if 'last_tab1_font_size' not in st.session_state:
    st.session_state['last_tab1_font_size'] = 50 # Default font size for burning SRT (Changed from 65)

# --- Helper Functions ---
def is_valid_url(url):
    # Basic check, can be expanded
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except ValueError:
        return False

def check_local_file(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"指定されたローカルファイルが存在しません: {file_path}")
    if not os.access(file_path, os.R_OK):
        raise PermissionError(f"ファイルに読み取り権限がありません: {file_path}")

# --- UI Classes ---
class ProgressManager:
    def __init__(self, key_suffix=""):
        # Removed the 'key' argument from st.progress
        self.progress_bar = st.progress(0)
        self.status_text = st.empty()

    def update(self, value, text):
        # Ensure value is between 0 and 100
        safe_value = max(0, min(100, int(value)))
        try:
            self.progress_bar.progress(safe_value)
            self.status_text.text(text)
        except Exception as e:
            # Handle potential errors if Streamlit elements become invalid (e.g., during reruns)
            logger.error(f"Error updating progress UI: {e}")


    def finish(self, text="完了！"):
        try:
            self.progress_bar.progress(100)
            self.status_text.text(text)
        except Exception as e:
            logger.error(f"Error finishing progress UI: {e}")

class ErrorHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def handle(self, error_message, user_message=None, prefix=""):
        full_error_msg = f"[{prefix}] {error_message}" if prefix else error_message
        self.logger.error(full_error_msg, exc_info=True) # Log traceback for better debugging
        display_message = user_message if user_message else f"エラーが発生しました: {error_message}"
        try:
            st.error(f"[{prefix}] {display_message}" if prefix else display_message)
            st.info("解決策: 入力パス/URL、ファイル権限、ffmpegのインストール状況、APIキー等を確認してください。詳細は process_log.log を参照。")
        except Exception as e:
             logger.error(f"Error displaying error message in Streamlit: {e}")


# --- Core Logic Functions ---
def download_video(video_url, output_base_path, progress_placeholder=None):
    """Downloads video using yt-dlp."""
    logger.info(f"Downloading video from {video_url} to base path {output_base_path}")
    downloaded_file_path = None
    try:
        # Define progress hook for yt-dlp
        def progress_hook(d):
            if d['status'] == 'downloading':
                percent_str = d.get('_percent_str', '0.0%').replace('%','')
                try:
                    percent = float(percent_str) / 100.0
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                    speed = d.get('_speed_str', 'N/A')
                    eta = d.get('_eta_str', 'N/A')
                    if progress_placeholder and total_bytes:
                         progress_placeholder.text(f"ダウンロード中: {percent:.1%} of {total_bytes/1024/1024:.1f}MB @ {speed} (ETA: {eta})")
                    elif progress_placeholder:
                         progress_placeholder.text(f"ダウンロード中: {percent:.1%} @ {speed} (ETA: {eta})")

                except ValueError:
                    pass # Ignore if percent string is not a float
            elif d['status'] == 'finished':
                 if progress_placeholder:
                     progress_placeholder.text("ダウンロード完了、ファイルを処理中...")
                 nonlocal downloaded_file_path # Access outer scope variable
                 downloaded_file_path = d.get('filename')


        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_base_path + ".%(ext)s",
            "merge_output_format": "mp4",
            "quiet": True,
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            "noprogress": True, # Disable default progress bar, use hook instead
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(video_url, download=True) # Hook sets downloaded_file_path

            # Verify the final file path after download and potential merge
            if downloaded_file_path and os.path.exists(downloaded_file_path):
                 logger.info(f"Download successful: {downloaded_file_path}")
                 return downloaded_file_path
            else:
                 # Fallback check if hook didn't capture filename correctly or merge happened
                 expected_mp4_path = output_base_path + ".mp4"
                 if os.path.exists(expected_mp4_path):
                     logger.info(f"Download successful (fallback check): {expected_mp4_path}")
                     return expected_mp4_path
                 else:
                     possible_files = glob.glob(output_base_path + ".*")
                     video_files = [f for f in possible_files if f.split('.')[-1] in ['mp4', 'mkv', 'webm', 'mov']]
                     if video_files:
                         logger.info(f"Download successful (glob check): {video_files[0]}")
                         return video_files[0]
                     else:
                         raise FileNotFoundError(f"yt-dlp downloaded, but final file not found for base: {output_base_path}")

    except yt_dlp.utils.DownloadError as e:
        error_handler.handle(f"動画ダウンロードエラー: {e}", prefix="Download")
        return None
    except Exception as e:
        error_handler.handle(f"予期せぬダウンロードエラー: {e}", prefix="Download")
        return None

# Updated signature: removed output_dir for Tab 1
def process_video(video_input, idx, progress_manager, subtitle_ext, generate_format, style_options, whisper_config, output_language, auto_font_size_enabled, manual_font_size, deepl_key, gemini_key):
    """Processes a single video: download (if URL), convert, transcribe, translate, generate subtitle content in memory."""
    video_start_time = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{idx:02}_{timestamp}"
    # Generate filename, but content will be in memory
    output_filename = f"{prefix}{subtitle_ext}"
    temp_wav_path = f"./{prefix}_temp.wav" # Keep temp files local
    downloaded_video_path = None # Keep track of downloaded file for cleanup
    audio_path_for_whisper = None # Path passed to Whisper
    video_path = None # Define video_path early

    progress_manager.update(0, f"[{prefix}] 処理開始: {video_input}")
    download_status_placeholder = st.empty() # Placeholder for download progress

    try:
        # --- 1. Get Video Path (Download or Local) ---
        if is_valid_url(video_input):
            progress_manager.update(5, f"[{prefix}] URLから動画をダウンロード準備中...")
            video_path = download_video(video_input, f"./{prefix}", download_status_placeholder)
            download_status_placeholder.empty() # Clear download status
            if not video_path:
                return None # Error handled in download_video
            downloaded_video_path = video_path # Mark for potential cleanup
            progress_manager.update(15, f"[{prefix}] ダウンロード完了: {os.path.basename(video_path)}")
        elif os.path.exists(video_input):
            check_local_file(video_input) # Check readability
            video_path = video_input
            progress_manager.update(15, f"[{prefix}] ローカルファイルを使用: {os.path.basename(video_path)}")
        else:
            raise FileNotFoundError(f"入力が見つかりません: {video_input}")

        # --- 2. Convert to WAV ---
        if not video_path.lower().endswith(".wav"):
            progress_manager.update(20, f"[{prefix}] 音声ファイルをWAV形式に変換中...")
            audio_path_for_whisper = convert_to_wav(video_path, temp_wav_path)
            if not audio_path_for_whisper:
                error_handler.handle(f"音声変換失敗 (ffmpeg)。ログを確認: process_log.log", prefix=prefix)
                return None # Error logged in convert_to_wav
            progress_manager.update(35, f"[{prefix}] WAV変換完了: {os.path.basename(audio_path_for_whisper)}")
        else:
            audio_path_for_whisper = video_path # Use original WAV
            progress_manager.update(35, f"[{prefix}] 入力はWAVファイルのため、変換をスキップ。")

        # --- 3. Transcribe ---
        progress_manager.update(40, f"[{prefix}] Whisperモデル ({whisper_config['model_size']}) 読み込み＆文字起こし中...")
        segments, info = transcribe_with_faster_whisper(
            audio_path_for_whisper,
            whisper_config["model_size"],
            "cpu", "int8", # Device and compute type
            whisper_config["beam_size"]
        )
        if segments is None: # Check if transcription failed in whisper_utils
             error_handler.handle(f"Whisper文字起こし失敗。ログを確認: process_log.log", prefix=prefix)
             return None

        progress_manager.update(80, f"[{prefix}] 文字起こし完了。言語: {info.language} ({info.language_probability:.2f})")

        if not segments:
            st.warning(f"[{prefix}] Whisperから字幕データが取得できませんでした。")
            return None # Or handle as needed

        # --- 4. Translate Segments (if necessary) ---
        source_lang_whisper = info.language # Get detected language from Whisper info
        target_lang_ui = output_language # Get selected language from UI

        target_lang_whisper_code = "ja" if target_lang_ui == "日本語" else "en"

        translated_segments = [] # Store potentially translated segments
        needs_translation = source_lang_whisper != target_lang_whisper_code
        translation_status = st.empty() # Placeholder for real-time translation status

        if needs_translation:
            progress_manager.update(82, f"[{prefix}] {source_lang_whisper} -> {target_lang_ui} 翻訳中...")
            translation_errors = 0
            for i, segment in enumerate(segments):
                original_text = segment.text if hasattr(segment, 'text') else segment.get('text', '')
                translated_text = None
                error_detail = None

                # Try DeepL first, passing the API key from args
                translated_text, error_detail = translate_text_deepl(
                    original_text, source_lang_whisper, target_lang_ui, deepl_api_key=deepl_key
                )

                # If DeepL fails (quota or other error), try Gemini, passing the API key from args
                if translated_text is None:
                    retry_message = f"[{prefix}] DeepL翻訳失敗 ({error_detail})。Geminiで再試行中 (セグメント {i+1}/{len(segments)})..."
                    translation_status.warning(retry_message)
                    logger.warning(f"[{prefix}] DeepL failed for segment {i}: {error_detail}. Trying Gemini.")

                    translated_text, error_detail = translate_text_gemini(
                        original_text, source_lang_whisper, target_lang_ui, gemini_api_key=gemini_key
                    )

                    if translated_text is None:
                        fail_message = f"[{prefix}] Gemini翻訳も失敗 ({error_detail})。原文を使用します (セグメント {i+1}/{len(segments)})。"
                        translation_status.error(fail_message)
                        logger.error(f"[{prefix}] Gemini also failed for segment {i}: {error_detail}. Using original text.")
                        translated_text = original_text # Use original text as fallback
                        translation_errors += 1

                # Update segment text (handle both object and dict)
                # Create new dicts to ensure immutability if segments were objects
                translated_segments.append({
                    'start': segment.start if hasattr(segment, 'start') else segment.get('start'),
                    'end': segment.end if hasattr(segment, 'end') else segment.get('end'),
                    'text': translated_text
                })

                # Update progress during translation
                if i % 5 == 0: # Update progress every 5 segments
                     progress_manager.update(82 + int(3 * (i / len(segments))), f"[{prefix}] 翻訳中... ({i+1}/{len(segments)})")

            segments = translated_segments # Replace original segments with translated ones
            translation_status.empty() # Clear the last status message after the loop
            if translation_errors > 0:
                 st.warning(f"[{prefix}] {translation_errors}件のセグメントで翻訳に失敗し、原文を使用しました。")
            progress_manager.update(85, f"[{prefix}] 翻訳完了。")
        else:
            translation_status.empty() # Clear status if translation was skipped
            st.info(f"[{prefix}] 文字起こし言語 ({source_lang_whisper}) と出力言語 ({target_lang_ui}) が同じため、翻訳をスキップします。")
            progress_manager.update(85, f"[{prefix}] 翻訳スキップ。")


        # --- 5. Generate Subtitle File ---
        progress_manager.update(86, f"[{prefix}] {generate_format} ファイルを作成中...") # Adjusted progress value
        try:
            # Determine video resolution first
            width, height = 1280, 720 # Default resolution
            try:
                logger.info(f"[{prefix}] Probing video for resolution: {video_path}")
                probe = ffmpeg.probe(video_path)
                video_info = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
                if video_info:
                    width = int(video_info.get('width', width))
                    height = int(video_info.get('height', height))
                    logger.info(f"[{prefix}] Detected resolution: {width}x{height}")
                else:
                     logger.warning(f"[{prefix}] No video stream found in probe for {video_path}. Using default resolution.")
            except Exception as probe_err:
                logger.warning(f"[{prefix}] ffmpeg.probe failed for {video_path}: {probe_err}. Using default resolution.")

            # --- Determine Final Font Size ---
            if auto_font_size_enabled:
                # Simple auto-calculation based on width (aim for ~30 chars wide)
                # Ensure width is positive
                safe_width = max(1, width)
                # Changed divisor from 30 to 40 for smaller auto font size
                final_font_size = max(10, int(safe_width / 40)) # Ensure minimum size 10
                logger.info(f"[{prefix}] Auto-calculated font size: {final_font_size} (based on width: {width})")
            else:
                final_font_size = manual_font_size # Use the manually provided size
                logger.info(f"[{prefix}] Using manual font size: {final_font_size}")

            # Store the determined font size in session state for Tab 2 (SRT burning)
            st.session_state['last_tab1_font_size'] = final_font_size
            logger.info(f"[{prefix}] Stored final font size {final_font_size} in session state.")

            # Generate content in memory and encode to bytes
            generated_content_bytes = None
            if generate_format == "SRTファイル（テキストのみ）":
                srt_content = generate_srt_content(segments, width=width, font_size=final_font_size)
                generated_content_bytes = srt_content.encode('utf-8')
            elif generate_format == "ASSファイル（装飾あり）":
                styles_data = load_styles()
                chosen_style_name = style_options.get("style_choice", "Default")
                show_bg = style_options.get("show_bg", False)
                if chosen_style_name not in styles_data:
                    st.warning(f"[{prefix}] スタイル '{chosen_style_name}' が styles.json に見つかりません。デフォルト設定を使用します。")
                    logger.warning(f"[{prefix}] Style '{chosen_style_name}' not found in styles.json. Using default.")
                    if 'Default' not in styles_data:
                         styles_data['Default'] = {
                             "Fontname": "Arial", "Fontsize": "20", "PrimaryColour": "&H00FFFFFF",
                             "SecondaryColour": "&H000000FF", "OutlineColour": "&H00000000", "BackColour": "&H80000000",
                             "Bold": "0", "Italic": "0", "Underline": "0", "StrikeOut": "0",
                             "ScaleX": "100", "ScaleY": "100", "Spacing": "0", "Angle": "0",
                             "BorderStyle": "1", "Outline": "1", "Shadow": "0",
                             "Alignment": "2", "MarginL": "10", "MarginR": "10", "MarginV": "10", "Encoding": "1"
                         }
                    chosen_style_name = "Default"
                header = generate_ass_header(width, height, styles_data, chosen_style_name, show_bg, font_size=final_font_size)
                # Pass styles_data to generate_ass_dialogue
                dialogue_lines = generate_ass_dialogue(segments, styles_data, chosen_style_name, width=width, font_size=final_font_size)
                ass_content = header + dialogue_lines
                generated_content_bytes = ass_content.encode('utf-8')
            elif generate_format == "FCPXMLファイル（Final Cut Pro用）":
                 fcpxml_content = generate_fcpxml(segments, video_path=video_path, font_size=final_font_size)
                 if fcpxml_content:
                     generated_content_bytes = fcpxml_content.encode('utf-8')
                 else:
                     raise ValueError("FCPXMLコンテンツの生成に失敗しました。")

            if generated_content_bytes is None:
                 raise ValueError("字幕コンテンツの生成に失敗しました (bytes is None)。")

            st.success(f"[{prefix}] {output_filename} 生成完了（メモリ内）")
            logger.info(f"[{prefix}] Successfully generated content for {output_filename} in memory")
            progress_manager.update(95, f"[{prefix}] {output_filename} 生成完了")

        except Exception as sub_err:
            error_handler.handle(f"字幕コンテンツ生成エラー: {sub_err}", prefix=prefix)
            return None # Stop processing this video

        # --- Store generated content info in session state for Tab 2 ---
        video_path_for_session = video_path # Use the determined video_path
        if video_path_for_session and os.path.exists(video_path_for_session):
             # Ensure the list exists before appending
             if 'generated_subtitles_data' not in st.session_state:
                 st.session_state['generated_subtitles_data'] = []
             # Append tuple: (video_path, subtitle_filename, subtitle_bytes)
             st.session_state['generated_subtitles_data'].append((str(video_path_for_session), output_filename, generated_content_bytes))
             logger.info(f"Added to session state 'generated_subtitles_data': ({str(video_path_for_session)}, {output_filename}, {len(generated_content_bytes)} bytes)")
        else:
             logger.warning(f"Could not determine valid video path for session state or path doesn't exist: {video_path_for_session}")

        # Return filename and content bytes (for Tab 1 download button)
        return (prefix, time.time() - video_start_time, output_filename, generated_content_bytes)

    except Exception as e:
        error_handler.handle(f"予期せぬエラー: {e}", prefix=prefix)
        return None
    finally:
        # --- Cleanup ---
        if audio_path_for_whisper and audio_path_for_whisper == temp_wav_path and os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
                logger.info(f"[{prefix}] Removed temporary WAV file: {temp_wav_path}")
            except OSError as e:
                logger.warning(f"[{prefix}] Failed to remove temporary WAV file '{temp_wav_path}': {e}")
        # --- DO NOT Clean up downloaded video file here ---


# Updated signature: removed output_dir
def main_process(video_inputs, progress_manager, subtitle_ext, generate_format, style_options, whisper_config, output_language, auto_font_size_enabled, manual_font_size, deepl_key, gemini_key):
    """Handles the overall processing flow for multiple videos."""
    processed_count = 0
    total_time = 0
    results = [] # Store results (prefix, time, filename, content_bytes) for each video

    st.markdown("---") # Separator before processing starts
    st.write(f"処理対象: {len(video_inputs)} 件")

    # Loop through all provided video inputs
    for idx, video_input in enumerate(video_inputs):
        # Create a new progress manager for each video? Or reuse? Reusing for now.
        st.markdown(f"---") # Separator for each video's log
        logger.info(f"Starting processing for video {idx+1}/{len(video_inputs)}: {video_input}")
        # Pass args down to process_video (no output_dir)
        result = process_video(
            video_input, idx + 1, progress_manager, subtitle_ext, generate_format,
            style_options, whisper_config, output_language,
            auto_font_size_enabled, manual_font_size,
            deepl_key, gemini_key
        )
        if result:
            # result is now (prefix, time, filename, content_bytes)
            results.append(result)
            processed_count += 1
            total_time += result[1] # Add elapsed time
        else:
             logger.error(f"Processing failed for video {idx+1}: {video_input}")
             st.error(f"動画 {idx+1} ({os.path.basename(video_input)}) の処理に失敗しました。詳細はログを確認してください。")
        # Reset progress for next video? Or show overall? Showing per-video progress.
        # If reusing progress_manager, maybe reset it here: progress_manager = ProgressManager()

    # Display summary after all videos are processed
    st.markdown("---") # Separator after processing finishes
    st.markdown("### ⏱️ 全体処理結果")
    if processed_count > 0:
        st.write(f"{len(video_inputs)} 件中 {processed_count} 件の処理が正常に完了しました。")
        st.write(f"合計処理時間: {total_time:.2f} 秒")
        st.markdown("#### 各動画の処理詳細:")
        # results contains (prefix, time, filename, content_bytes)
        for name, t, filename, _ in results: # Unpack filename, ignore bytes for summary
            st.write(f"- **{name}**: {t:.2f} 秒 (ファイル名: {filename})")
    else:
        st.warning("処理が正常に完了した動画はありませんでした。")
    logger.info(f"Main process finished. Returning {len(results)} results.") # Log before returning
    return results # Return the populated list


# --- Main Streamlit App ---
# Try loading .env without explicit path
load_dotenv()
# Load API keys early for potential use in UI logic if needed
openai_api_key = os.getenv("OPENAI_API_KEY")
# deepl_api_key = os.getenv("DEEPL_API_KEY") # Removed - Get from UI
# gemini_api_key = os.getenv("GEMINI_API_KEY") # Removed - Get from UI
error_handler = ErrorHandler()

st.set_page_config(page_title="一撃！字幕焼き込みくん4", page_icon="🎬", layout="wide") # Use wide layout
st.title("一撃！字幕焼き込みくん4")

# --- API Key Inputs ---
st.subheader("APIキー設定")
col_api1, col_api2 = st.columns(2)
with col_api1:
    deepl_api_key_input = st.text_input("DeepL API Key:", type="password", key="deepl_api_key_input", help="DeepL APIキー (FreeまたはPro) を入力してください。")
with col_api2:
    gemini_api_key_input = st.text_input("Gemini API Key:", type="password", key="gemini_api_key_input", help="Google AI Studioで取得したGemini APIキーを入力してください。")
st.markdown("---") # Separator

tab1, tab2 = st.tabs(["🎤 字幕ファイル作成", "🔥 字幕焼き込み"])

# --- Tab 1: Subtitle Generation ---
with tab1:
    results = [] # Initialize results list here
    st.header("1. 入力ファイルの指定")
    # Removed radio button - show both inputs

    # --- URL Input Section ---
    st.subheader("URLから入力")
    url_input = st.text_area(
        "動画のURLを1行ずつ入力:",
        placeholder="例:\nhttps://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://vimeo.com/...",
        height=100,
        key="tab1_url_input"
    )
    url_video_inputs = [line.strip() for line in url_input.splitlines() if line.strip() and is_valid_url(line.strip())]
    # Log invalid URLs entered? Optional.

    # --- File Uploader Section ---
    st.subheader("ローカルファイルからアップロード")
    uploaded_files = st.file_uploader(
        "動画・音声ファイルを選択 (複数可):",
        type=["mp4", "mov", "mkv", "avi", "wmv", "flv", "webm", "wav", "mp3", "m4a"], # Allow common video/audio
        accept_multiple_files=True,
        key="tab1_file_uploader"
    )
    # Define persistent directory for uploads
    persistent_upload_dir = Path("./persistent_videos")
    try:
        persistent_upload_dir.mkdir(parents=True, exist_ok=True) # Create directory if it doesn't exist
        logger.info(f"Ensured persistent upload directory exists: {persistent_upload_dir.resolve()}")
    except OSError as e:
        st.error(f"アップロード用ディレクトリの作成に失敗しました: {persistent_upload_dir}. アプリケーションを再起動するか、権限を確認してください。")
        logger.error(f"Failed to create persistent upload directory '{persistent_upload_dir}': {e}")
        st.stop() # Stop execution if directory cannot be created

    # Initialize video_inputs list *before* the loop to ensure correct scope
    video_inputs = []

    if uploaded_files:
        for file in uploaded_files:
            # Sanitize filename to prevent path traversal or invalid characters
            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", file.name)
            # Create a unique filename to avoid collisions
            unique_filename = f"uploaded_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_filename}"
            path = persistent_upload_dir / unique_filename # Use Path object for joining
            try:
                with open(path, "wb") as f:
                    f.write(file.getbuffer())
                absolute_path = path.resolve() # Get the absolute path
                st.success(f"アップロード完了: {file.name} -> {path.name} (保存先: {absolute_path})")
                video_inputs.append(str(absolute_path)) # Append the string representation of the ABSOLUTE path
                logger.info(f"Saved uploaded file {file.name} to persistent path: {absolute_path}")
            except Exception as e:
                st.error(f"ファイル保存失敗 ({file.name}): {e}")
                logger.error(f"Failed to save uploaded file {file.name} to {path}: {e}")

    # Combine inputs from both methods
    uploaded_video_paths = [] # Store paths of successfully uploaded files
    if uploaded_files:
        for file in uploaded_files:
            # Reuse the saving logic (already adds to persistent_upload_dir)
            # Sanitize filename
            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", file.name)
            # Create a unique filename
            unique_filename = f"uploaded_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_filename}"
            path = persistent_upload_dir / unique_filename
            try:
                # Check if already saved (Streamlit might rerun script on interaction)
                # This check might be complex due to unique names, rely on video_inputs list below
                # Instead of saving again here, we retrieve paths from the earlier loop
                # Find the corresponding path in video_inputs based on original filename? Risky.
                # Let's assume the earlier loop correctly populated video_inputs with absolute paths
                # We just need to get those paths.
                # The `video_inputs` list is populated correctly in the loop above.
                pass # Paths are already added to video_inputs list above
            except Exception as e:
                 # This block might not be needed if we rely on the first loop
                 st.error(f"ファイル処理エラー ({file.name}): {e}")
                 logger.error(f"Error processing uploaded file {file.name} after initial save: {e}")

    # Combine URL inputs file paths (absolute paths)
    # The `video_inputs` list already contains the absolute paths from the upload loop.
    # We need to add the valid URLs to this list.
    final_video_inputs = video_inputs + url_video_inputs
    # Log the combined list for debugging
    logger.info(f"Combined video inputs for processing: {final_video_inputs}")


    st.header("2. 出力設定")
    # Use 4 columns for horizontal layout
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        generate_format = st.selectbox(
            "字幕ファイル形式:",
            ["SRTファイル（テキストのみ）", "ASSファイル（装飾あり）", "FCPXMLファイル（Final Cut Pro用）"],
            key="tab1_format"
        )
        # Determine subtitle extension based on format
        if generate_format == "SRTファイル（テキストのみ）":
            subtitle_ext = ".srt"
        elif generate_format == "ASSファイル（装飾あり）":
            subtitle_ext = ".ass"
        else: # FCPXML
            subtitle_ext = ".fcpxml"

    with col2:
        output_language = st.selectbox(
            "出力言語:",
            ["日本語", "英語"],
            key="tab1_output_lang"
        )

    with col3:
        # --- Font Size Input with Auto Option ---
        auto_font_size = st.checkbox("フォントサイズ自動調整", value=True, key="tab1_auto_font_size", help="動画の幅に基づいてフォントサイズを自動調整します。チェックを外すと手動で指定できます。")

        # Use session state to remember the last manual value if user toggles auto off/on
        if 'manual_font_size' not in st.session_state:
            st.session_state.manual_font_size = 50 # Default manual value (Changed from 65)

        # Store the current manual input value
        manual_font_size_input = st.number_input(
            "フォントサイズ (手動):",
            min_value=10, max_value=200,
            value=st.session_state.manual_font_size, # Use remembered value
            key="tab1_manual_font_size_input",
            disabled=auto_font_size, # Disable if auto is checked
            help="自動調整がオフの場合に適用されます。"
        )
        # Update the remembered manual value only if it's changed and not disabled
        if not auto_font_size:
             st.session_state.manual_font_size = manual_font_size_input

        # The actual font_size used will be determined later in process_video
        # For now, just capture the state of auto and the manual value
        # We'll retrieve these values using their keys inside process_video

    with col4:
        whisper_mode = st.selectbox(
            "文字起こし精度:",
            ["バランス (medium)", "高精度 (large)"], index=0, key="tab1_whisper_mode"
        )
        whisper_config = {
            "beam_size": 5, # Keep beam size consistent for simplicity or adjust based on mode
            "model_size": "large" if whisper_mode == "高精度 (large)" else "medium"
        }

    # Style options for ASS (only show if ASS is selected) - Placed below columns
    style_options = {"style_choice": None, "show_bg": False}
    styles = {} # Define styles dict here
    if generate_format == "ASSファイル（装飾あり）":
        st.subheader("ASS スタイル設定") # Keep subheader outside columns
        styles = load_styles() # Load styles from styles.json
        if styles:
             if 'Default' not in styles:
                 styles['Default'] = {
                     "Fontname": "Arial", "Fontsize": "20", "PrimaryColour": "&H00FFFFFF",
                     "SecondaryColour": "&H000000FF", "OutlineColour": "&H00000000", "BackColour": "&H80000000",
                     "Bold": "0", "Italic": "0", "Underline": "0", "StrikeOut": "0",
                     "ScaleX": "100", "ScaleY": "100", "Spacing": "0", "Angle": "0",
                     "BorderStyle": "1", "Outline": "1", "Shadow": "0",
                     "Alignment": "2", "MarginL": "10", "MarginR": "10", "MarginV": "10", "Encoding": "1"
                 }
             # Use columns for style selection and checkbox as well? Or keep below? Keeping below for now.
             style_options["style_choice"] = st.selectbox("適用スタイル:", options=list(styles.keys()), key="tab1_style_choice")
             style_options["show_bg"] = st.checkbox("字幕背景を表示する", value=True, key="tab1_show_bg")
        else:
             st.warning("styles.json が見つからないか空です。基本的なデフォルトスタイルを使用します。")
             styles['Default'] = {
                 "Fontname": "Arial", "Fontsize": "20", "PrimaryColour": "&H00FFFFFF",
                 "SecondaryColour": "&H000000FF", "OutlineColour": "&H00000000", "BackColour": "&H80000000",
                 "Bold": "0", "Italic": "0", "Underline": "0", "StrikeOut": "0",
                 "ScaleX": "100", "ScaleY": "100", "Spacing": "0", "Angle": "0",
                 "BorderStyle": "1", "Outline": "1", "Shadow": "0",
                 "Alignment": "2", "MarginL": "10", "MarginR": "10", "MarginV": "10", "Encoding": "1"
             }
             style_options["style_choice"] = "Default" # Fallback to the defined default

    st.header("3. 実行")
    button_label = f"字幕ファイル ({subtitle_ext}) 生成開始"
    process_button_clicked = st.button(button_label, key="tab1_process_button")

    # Placeholder for progress bar and status text - Recreate here for each run?
    progress_manager = ProgressManager(key_suffix="tab1")

    if process_button_clicked:
        # Use the combined list 'final_video_inputs'
        if final_video_inputs:
            if generate_format == "ASSファイル（装飾あり）" and not style_options.get("style_choice"):
                 st.error("ASSスタイルが選択されていません。styles.jsonを確認するか、デフォルトスタイルを使用します。")
                 if 'Default' in styles:
                     style_options["style_choice"] = "Default"
                     logger.info("Forcing default style for ASS generation.")
                 else:
                     st.error("デフォルトスタイルも定義されていません。処理を中止します。")
                     st.stop()

            # Retrieve the state of the auto checkbox and the manual input value
            auto_font_size_enabled = st.session_state.tab1_auto_font_size
            manual_font_size_value = st.session_state.tab1_manual_font_size_input

            # Note: We no longer store the potentially outdated 'font_size' variable here.
            # The final font size determination and storage happens inside process_video.
            # st.session_state['last_tab1_font_size'] = font_size # Removed
            # logger.info(f"Stored font size {font_size} in session state.") # Removed

            # Get keys from UI inputs
            deepl_key_from_ui = st.session_state.deepl_api_key_input
            gemini_key_from_ui = st.session_state.gemini_api_key_input

            # Basic check if keys are entered
            if not deepl_key_from_ui and not gemini_key_from_ui:
                 st.warning("DeepLまたはGeminiのAPIキーが入力されていません。翻訳が必要な場合、処理が失敗する可能性があります。")
            elif not deepl_key_from_ui:
                 st.warning("DeepL APIキーが入力されていません。DeepLでの翻訳はスキップされます。")
            elif not gemini_key_from_ui:
                 st.warning("Gemini APIキーが入力されていません。DeepL失敗時のGeminiでの再試行はスキップされます。")

            # Call main_process with the combined list
            results = main_process(
                final_video_inputs, progress_manager, subtitle_ext, generate_format,
                style_options, whisper_config, output_language,
                auto_font_size_enabled, manual_font_size_value,
                deepl_key_from_ui, gemini_key_from_ui # Pass keys from UI
            )
            # --- Display Download Buttons for Generated Subtitles (Moved inside if video_inputs) ---
            if results: # Check if main_process returned any results (list of tuples: prefix, time, filename, content_bytes)
                st.markdown("---")
                st.subheader("✅ 生成されたファイル")
                # Use columns for better layout? Maybe 2 columns.
                col_dl1, col_dl2 = st.columns(2)
                current_col = col_dl1 # Start with the first column

                for i, (_, _, filename, content_bytes) in enumerate(results):
                    if content_bytes:
                        try:
                            # Determine mime type based on filename extension
                            mime_type = 'text/plain' # Default
                            if filename.lower().endswith('.srt'):
                                mime_type = 'text/plain' # or 'application/x-subrip'
                            elif filename.lower().endswith('.ass'):
                                mime_type = 'text/plain' # ASS is also plain text
                            elif filename.lower().endswith('.fcpxml'):
                                mime_type = 'application/xml'

                            # Display download button in the current column
                            with current_col:
                                st.download_button(
                                    label=f"ダウンロード: {filename}",
                                    data=content_bytes, # Pass bytes directly
                                    file_name=filename, # Suggest original filename
                                    mime=mime_type,
                                    key=f"download_{i}_{filename}" # Unique key using filename
                                )
                                # Alternate columns
                                current_col = col_dl2 if current_col == col_dl1 else col_dl1

                        except Exception as btn_err:
                             # Error during button creation itself (less likely)
                             st.error(f"ダウンロードボタン作成エラー ({filename}): {btn_err}")
                             logger.error(f"Error creating download button for {filename}: {btn_err}")
                    else:
                        # This case should ideally not happen if process_video returns correctly
                        st.warning(f"ファイルコンテンツが見つかりません（メモリ内）: {filename}")
                        logger.warning(f"Content bytes not found for {filename} in results list.")
        # This else block corresponds to 'if final_video_inputs:'
        else:
            st.warning("処理する動画URLまたはファイルが指定されていません。")


# --- Tab 2: Burn Subtitles ---
with tab2:
    st.header("動画に字幕を焼き込む")

    burn_source_option = st.radio(
        "焼き込み対象の選択:",
        ["字幕ファイル作成タブで生成したファイルを使用", "個別にファイル指定"], # Renamed option
        key="tab2_source_option",
        horizontal=True
    )

    video_subtitle_pairs = [] # List to hold pairs: (video_path, subtitle_path)
    output_filenames = {} # Dictionary to store suggested output names {video_path: output_name}
    subtitle_data_for_burn = {} # Store subtitle filename and bytes: {video_path: (sub_filename, sub_bytes)}

    if burn_source_option == "字幕ファイル作成タブで生成したファイルを使用": # Renamed condition
        st.subheader("字幕ファイル作成タブで生成されたファイル:") # Renamed subheader
        # Use the new session state key
        if not st.session_state.get('generated_subtitles_data'):
            st.info("字幕ファイル作成タブでまだ字幕ファイルが生成されていません。") # Renamed info text
        else:
            # --- Debugging Logs Start ---
            session_data = st.session_state.get('generated_subtitles_data', [])
            logger.info(f"[Tab 2 Debug] Session state 'generated_subtitles_data': {session_data}")
            logger.info("[Tab 2 Debug] Checking existence of video paths in session state:")
            for i, (v_path, s_filename, _) in enumerate(session_data):
                exists = os.path.exists(v_path) if v_path else False
                logger.info(f"[Tab 2 Debug]   Pair {i}: Path='{v_path}', Exists={exists}")
            # --- Debugging Logs End ---

            # Filter out data where video file might no longer exist (less likely in cloud but good practice)
            valid_generated_data = [
                (v_path, s_filename, s_bytes) for v_path, s_filename, s_bytes
                in session_data # Use the variable we already retrieved
                if v_path and os.path.exists(v_path) # Check if original video path still exists
            ]
            logger.info(f"[Tab 2 Debug] Filtered valid_generated_data count: {len(valid_generated_data)}") # Log count after filtering

            # Create options for multiselect: "Video Name + Subtitle Name" -> (video_path, (sub_filename, sub_bytes))
            generated_files_options = {
                f"{os.path.basename(v_path)} + {s_filename}": (v_path, (s_filename, s_bytes))
                for v_path, s_filename, s_bytes in valid_generated_data
            }

            if not generated_files_options:
                 st.warning("有効な生成済みデータペアが見つかりません。タブ1で再生成するか、ファイルパスを確認してください。")
            else:
                selected_pairs_display = st.multiselect(
                    "焼き込むペアを選択:",
                    options=list(generated_files_options.keys()),
                    key="tab2_generated_select"
                )
                # video_subtitle_pairs will now contain tuples of (video_path, (sub_filename, sub_bytes))
                video_subtitle_pairs = [generated_files_options[key] for key in selected_pairs_display]

                # Populate output_filenames based on selected pairs
                for video_path, (sub_filename, _) in video_subtitle_pairs:
                     base, _ = os.path.splitext(os.path.basename(video_path))
                     sub_ext = os.path.splitext(sub_filename)[1] # Get extension from filename
                     output_filenames[video_path] = f"{base}{sub_ext.replace('.', '_')}_burned.mp4"


    elif burn_source_option == "個別にファイル指定":
        st.subheader("個別にファイルを指定:")
        burn_video_input = st.text_input("動画ファイルのパスまたはURL:", key="tab2_burn_video_individual")
        uploaded_subtitle_individual = st.file_uploader(
            "字幕ファイル (.srt または .ass):",
            type=["ass", "srt"],
            key="tab2_subtitle_upload_individual"
        )
        if burn_video_input and uploaded_subtitle_individual:
             st.info("個別指定の複数ファイル対応は現在制限されています。「字幕ファイル作成タブで生成したファイルを使用」を推奨します。")
             # Read the uploaded subtitle file bytes
             sub_bytes_individual = uploaded_subtitle_individual.getvalue()
             sub_filename_individual = uploaded_subtitle_individual.name
             # Store in the same format: (video_path, (sub_filename, sub_bytes))
             video_subtitle_pairs = [(burn_video_input, (sub_filename_individual, sub_bytes_individual))]
             base, _ = os.path.splitext(os.path.basename(burn_video_input)) if not is_valid_url(burn_video_input) else ("downloaded_video", "")
             sub_ext = os.path.splitext(sub_filename_individual)[1]
             output_filenames[burn_video_input] = f"{base}{sub_ext.replace('.', '_')}_burned.mp4"

    # Removed font size input from Tab 2

    st.header("実行")
    if video_subtitle_pairs:
        st.markdown("以下のペアで焼き込み処理を実行します:")
        # video_subtitle_pairs now contains (video_path, (sub_filename, sub_bytes)) or (video_path, UploadedFile)
        for video_path, subtitle_info_tuple_or_obj in video_subtitle_pairs:
             out_name = output_filenames.get(video_path, "不明な出力ファイル名")
             # Extract subtitle filename for display
             if isinstance(subtitle_info_tuple_or_obj, tuple):
                 sub_display_name = subtitle_info_tuple_or_obj[0] # Get filename from tuple
             elif hasattr(subtitle_info_tuple_or_obj, 'name'): # Handle UploadedFile object
                 sub_display_name = subtitle_info_tuple_or_obj.name
             else:
                 sub_display_name = "不明な字幕ファイル"

             st.write(f"- 動画: `{os.path.basename(video_path)}`")
             st.write(f"- 字幕: `{sub_display_name}`")
             st.write(f"- 出力: `{out_name}`")
             st.markdown("---")

    if st.button("字幕焼き込み開始", key="tab2_burn_button", disabled=not video_subtitle_pairs):

        burn_progress_overall = st.progress(0)
        burn_status_overall = st.empty()
        total_pairs = len(video_subtitle_pairs)
        processed_success_count = 0
        successful_burns = [] # Initialize list here

        for i, (video_input_path, subtitle_info) in enumerate(video_subtitle_pairs):

            pair_prefix = f"ペア {i+1}/{total_pairs}"
            burn_status_overall.text(f"{pair_prefix}: 処理開始...")

            subtitle_temp_path = None
            downloaded_burn_video = None
            burn_video_path = video_input_path
            # Generate a temporary file path for the output video
            # Keep the original base name for the suggested download filename
            base_output_name = output_filenames.get(video_input_path, f"output_{i+1}_burned.mp4")
            try:
                # Create a temporary file that persists until closed/deleted
                # Suffix helps identify the file type if needed, delete=False keeps it after close
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_video_file:
                    output_path_burn_temp = temp_video_file.name # Get the temporary path
                logger.info(f"[{pair_prefix}] Determined temporary burn output path: {output_path_burn_temp}")
            except Exception as temp_err:
                st.error(f"[{pair_prefix}] 一時ファイルの作成に失敗しました: {temp_err}")
                logger.error(f"[{pair_prefix}] Failed to create temporary output file: {temp_err}")
                continue # Skip this pair

            try:
                # --- 1. Prepare Subtitle File ---
                if isinstance(subtitle_info, tuple) and len(subtitle_info) == 2:
                    # Handles the tuple (filename, bytes) passed from Tab 1 via session state
                    sub_filename, sub_bytes = subtitle_info
                    # Ensure filename is just the name, not potential path parts if any were included
                    safe_sub_filename = os.path.basename(sub_filename)
                    subtitle_temp_path = f"./temp_burn_{safe_sub_filename}" # Use original filename for temp name
                    with open(subtitle_temp_path, "wb") as f:
                        f.write(sub_bytes)
                    logger.info(f"[{pair_prefix}] Saved subtitle bytes from session state ('{safe_sub_filename}') to temporary file: {subtitle_temp_path}")
                elif isinstance(subtitle_info, str) and os.path.exists(subtitle_info):
                    # Handles the case where subtitle_info is a path string (less likely now)
                    subtitle_temp_path = f"./temp_burn_{os.path.basename(subtitle_info)}"
                    shutil.copy2(subtitle_info, subtitle_temp_path)
                    logger.info(f"[{pair_prefix}] Copied subtitle file {subtitle_info} to {subtitle_temp_path}")
                elif hasattr(subtitle_info, 'name') and hasattr(subtitle_info, 'getbuffer'):
                    # Handles the case where subtitle_info is an UploadedFile object (from individual upload)
                    subtitle_temp_path = f"./temp_burn_{subtitle_info.name}"
                    with open(subtitle_temp_path, "wb") as f:
                        f.write(subtitle_info.getbuffer())
                    logger.info(f"[{pair_prefix}] Saved uploaded subtitle ('{subtitle_info.name}') to {subtitle_temp_path}")
                else:
                    # If none of the above match, then it's invalid
                    st.error(f"[{pair_prefix}] 無効な字幕ファイル情報形式です: {type(subtitle_info)}")
                    logger.error(f"[{pair_prefix}] Invalid subtitle info type: {type(subtitle_info)}, value: {subtitle_info}")
                    continue

                # --- 2. Prepare Video File ---
                if is_valid_url(video_input_path):
                    burn_status_overall.text(f"{pair_prefix}: 動画ダウンロード中...")
                    downloaded_burn_video = download_video(video_input_path, f"./temp_burn_video_{i+1}", burn_status_overall) # Pass status placeholder
                    burn_status_overall.text(f"{pair_prefix}: 動画ダウンロード完了後処理中...") # Update status after download
                    if not downloaded_burn_video:
                        st.error(f"[{pair_prefix}] 動画のダウンロードに失敗しました: {video_input_path}")
                        continue
                    burn_video_path = downloaded_burn_video
                elif not os.path.exists(burn_video_path):
                     st.error(f"[{pair_prefix}] 動画ファイルが見つかりません: {burn_video_path}")
                     continue

                # --- 3. Probe Video for Resolution ---
                width, height = 1280, 720
                is_vertical = False
                try:
                    logger.info(f"[{pair_prefix}] Probing video for burn: {burn_video_path}")
                    probe = ffmpeg.probe(burn_video_path)
                    video_info = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
                    if video_info:
                        width = int(video_info.get('width', width))
                        height = int(video_info.get('height', height))
                        is_vertical = height > width
                        logger.info(f"[{pair_prefix}] Detected resolution: {width}x{height} (Vertical: {is_vertical})")
                    else:
                         logger.warning(f"[{pair_prefix}] No video stream found in probe for {burn_video_path}.")
                except Exception as probe_err:
                    logger.warning(f"[{pair_prefix}] ffmpeg.probe failed for {burn_video_path}: {probe_err}. Using default resolution.")

                # --- 4. Prepare ffmpeg Command ---
                burn_status_overall.text(f"{pair_prefix}: 字幕焼き込み処理準備中...")
                logger.info(f"[{pair_prefix}] Starting subtitle burn: Input='{burn_video_path}', Subs='{subtitle_temp_path}', Output='{output_path_burn_temp}'")

                subtitle_filter_path = os.path.abspath(subtitle_temp_path)
                # More robust escaping for Windows paths in ffmpeg filters
                subtitle_filter_path_escaped = subtitle_filter_path.replace('\\', '/').replace(':', '\\\\:')

                vf_filter_list = []
                font_style_options = [] # For force_style

                # Get font size from session state (set in Tab 1) - Use default if not found
                srt_burn_font_size = st.session_state.get('last_tab1_font_size', 50) # Changed default from 65
                font_style_options.append(f"FontSize={srt_burn_font_size}")

                if is_vertical:
                     margin_v_v = max(10, int(width * 0.05))
                     font_style_options.append(f"MarginV={margin_v_v}")
                     font_style_options.append("Alignment=8") # Top Center for vertical

                force_style_value = ",".join(font_style_options)

                if subtitle_temp_path.lower().endswith(".ass"):
                     # For ASS, generally avoid force_style unless absolutely necessary
                     vf_filter_list.append(f"ass='{subtitle_filter_path_escaped}'")
                     logger.info(f"[{pair_prefix}] [ASS Burn Debug] Using ASS filter: ass='{subtitle_filter_path_escaped}'") # Debug Log
                     if is_vertical:
                          logger.warning(f"[{pair_prefix}] Vertical video detected with ASS. Styles might need manual adjustment in ASS file or styles.json for best results.")
                else: # .srt
                     # Apply force_style for SRT, including font size and vertical adjustments
                     vf_filter_list.append(f"subtitles='{subtitle_filter_path_escaped}':force_style='{force_style_value}'")
                     logger.info(f"[{pair_prefix}] [SRT Burn Debug] Applying force_style for SRT: {force_style_value}") # Debug Log

                final_vf_filter = ",".join(vf_filter_list)
                logger.info(f"[{pair_prefix}] [FFmpeg Burn Debug] Final vf filter string: {final_vf_filter}") # Debug Log

                # --- 5. Run ffmpeg Process ---
                burn_status_overall.text(f"{pair_prefix}: 字幕焼き込み実行中...")
                process = ffmpeg.input(burn_video_path).output(
                    output_path_burn_temp, # Use the temporary output path
                    vf=final_vf_filter,
                    vcodec="libx264", preset="medium", crf=23,
                    acodec="aac", audio_bitrate="192k", strict="-2"
                ).overwrite_output().run_async(pipe_stdout=True, pipe_stderr=True)

                stdout, stderr = process.communicate() # Wait for completion

                if process.returncode == 0:
                    st.success(f"[{pair_prefix}] 字幕焼き込み完了 (一時ファイル: {os.path.basename(output_path_burn_temp)})")
                    logger.info(f"[{pair_prefix}] Subtitle burn successful to temporary file: {output_path_burn_temp}")
                    processed_success_count += 1
                    # Store the temporary path and the original intended filename for the download button
                    successful_burns.append((output_path_burn_temp, base_output_name))
                else:
                    error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "不明なFFmpegエラー"
                    st.error(f"[{pair_prefix}] 字幕焼き込み中にエラーが発生しました。")
                    st.text_area(f"FFmpeg エラー詳細 ({os.path.basename(video_input_path)}):", error_msg, height=150)
                    logger.error(f"[{pair_prefix}] FFmpeg subtitle burn failed for {output_path_burn_temp}. Stderr:\n{error_msg}") # Corrected variable

            except Error as e:
                error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else "ffmpeg-pythonエラー"
                st.error(f"[{pair_prefix}] FFmpeg実行エラーが発生しました。")
                st.text_area(f"FFmpeg エラー詳細 ({os.path.basename(video_input_path)}):", error_msg, height=150)
                logger.error(f"[{pair_prefix}] ffmpeg-python error during burn for {output_path_burn_temp}: {error_msg}") # Corrected variable
            except Exception as e:
                st.error(f"[{pair_prefix}] 字幕焼き込み中に予期せぬエラーが発生しました: {e}")
                logger.exception(f"[{pair_prefix}] Unexpected error during subtitle burn process.")
            finally:
                # --- Cleanup Pair ---
                if subtitle_temp_path and os.path.exists(subtitle_temp_path):
                    try:
                        os.remove(subtitle_temp_path)
                        logger.info(f"[{pair_prefix}] Removed temporary subtitle file: {subtitle_temp_path}")
                    except OSError as e:
                         logger.warning(f"[{pair_prefix}] Failed to remove temporary subtitle file '{subtitle_temp_path}': {e}")
                if downloaded_burn_video and os.path.exists(downloaded_burn_video):
                    try:
                        os.remove(downloaded_burn_video)
                        logger.info(f"[{pair_prefix}] Removed temporary downloaded video: {downloaded_burn_video}")
                    except OSError as e:
                         logger.warning(f"[{pair_prefix}] Failed to remove temporary downloaded video '{downloaded_burn_video}': {e}")

            # Update overall progress
            burn_progress_overall.progress((i + 1) / total_pairs)

        # Final status update
        burn_status_overall.text(f"全 {total_pairs} ペアの処理完了。{processed_success_count} 件成功。")
        if processed_success_count == total_pairs and total_pairs > 0:
             st.balloons()

        # --- Add Download Buttons for Burned Videos ---
        if successful_burns:
            st.markdown("---")
            st.subheader("✅ 焼き込み済み動画のダウンロード")
            col_burn_dl1, col_burn_dl2 = st.columns(2) # Use columns for layout
            current_burn_col = col_burn_dl1

            for temp_path, final_name in successful_burns:
                if os.path.exists(temp_path):
                    try:
                        with open(temp_path, "rb") as fp:
                            btn = current_burn_col.download_button(
                                label=f"ダウンロード: {final_name}",
                                data=fp, # Pass file object directly (more efficient for large files)
                                file_name=final_name,
                                mime="video/mp4",
                                key=f"download_burn_{final_name}" # Unique key
                            )
                        # Alternate columns
                        current_burn_col = col_burn_dl2 if current_burn_col == col_burn_dl1 else col_burn_dl1
                    except Exception as e:
                        st.error(f"ダウンロードボタン作成エラー ({final_name}): {e}")
                        logger.error(f"Error creating download button for burned video {final_name} from {temp_path}: {e}")
                else:
                    logger.warning(f"Burned video temporary file not found for download: {temp_path} (intended name: {final_name})")
                    st.warning(f"焼き込み済みファイルが見つかりません: {final_name}")
