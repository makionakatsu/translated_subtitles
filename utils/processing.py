"""Processing utilities extracted from main.py.

This module centralises video downloading, audio conversion, transcription,
translation and subtitle generation so that Streamlit UI remains lightweight.
"""

# --- Imports (mirroring main.py's requirements) ---
import streamlit as st
from utils.video_utils import convert_to_wav
from utils.whisper_utils import transcribe_with_faster_whisper
from utils.translate_utils import translate_text_deepl, translate_text_gemini
import ffmpeg
import os
from urllib.parse import urlparse
import yt_dlp
import json
from ffmpeg import Error
import requests
import textwrap
from datetime import datetime, time, timedelta
import glob
import re
from xml.etree.ElementTree import Element, SubElement, ElementTree
import xml.dom.minidom
import time
from pathlib import Path
from utils.fcpxml_utils import generate_fcpxml

# === Moved functions ===
# --- Subtitle writers -------------------------------------------------
def _format_timestamp(sec: float) -> str:
    """sec (float) -> 'HH:MM:SS,mmm'"""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    ms = int(round((s - int(s)) * 1000))
    return f"{int(h):02}:{int(m):02}:{int(s):02},{ms:03}"

def _write_srt(segments, out_path: Path):
    """Write segments to .srt"""
    with out_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_timestamp(seg.start)
            end   = _format_timestamp(seg.end)
            raw_text = getattr(seg, "text", "") or ""
            text = raw_text.strip().replace("\n", " ")
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

def _write_ass(segments, out_path: Path, font_size: int):
    """Write segments to .ass"""
    with out_path.open("w", encoding="utf-8") as f:
        # Script Info
        f.write("[Script Info]\n")
        f.write("ScriptType: v4.00+\n")
        f.write("Collisions: Normal\n")
        f.write("PlayResX: 1920\n")
        f.write("PlayResY: 1080\n")
        f.write("\n")
        # Styles
        f.write("[V4+ Styles]\n")
        f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, " 
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
        f.write(f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n")
        f.write("\n")
        # Events
        f.write("[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        for seg in segments:
            start = _format_timestamp(seg.start).replace(',', '.')
            end = _format_timestamp(seg.end).replace(',', '.')
            raw_text = getattr(seg, "text", "") or ""
            text = raw_text.strip().replace("\n", "\\N")
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

def is_valid_url(url):
    """Checks if a string is a valid HTTP/HTTPS URL."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def check_local_file(path):
    """Checks if a local file exists and is accessible."""
    return os.path.isfile(path) and os.access(path, os.R_OK)


def download_video(url, output_dir="./", prefix=""):
    """
    Downloads a video from a URL using yt_dlp and returns the local path.
    Shows progress in Streamlit while downloading.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}{timestamp}.mp4"
    output_path = os.path.join(output_dir, filename)

    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "postprocessors": [
            {"key": "FFmpegMerger"},
            {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
        ],
        "quiet": True,
        "progress_hooks": [],
    }

    # Streamlit progress bar
    progress_bar = st.progress(0)
    progress_text = st.empty()

    def progress_hook(d):
        if d["status"] == "downloading":
            progress = d.get("_percent_str", "").strip()
            try:
                percent = float(progress.replace("%", ""))
                progress_bar.progress(min(max(percent / 100.0, 0.0), 1.0))
                progress_text.text(f"Downloading… {progress}")
            except ValueError:
                pass
        elif d["status"] == "finished":
            progress_bar.progress(1.0)
            progress_text.text("Download completed")

    ydl_opts["progress_hooks"].append(progress_hook)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                # Fallback when requested MP4 is not available
                if "Requested format is not available" in str(e):
                    st.warning("MP4 が取得できなかったため汎用フォーマットで再試行します")
                    ydl_opts["format"] = "bestvideo+bestaudio/best"
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                        ydl_retry.download([url])
                else:
                    raise
        return output_path
    except KeyError as e:
        # Merge時のKeyErrorをキャッチして単純なbestフォーマットで再試行
        st.warning(f"フォーマット処理中にエラーが発生したため、ベストフォーマットで再試行します: {e}")
        simple_opts = {"outtmpl": output_path, "format": "best", "quiet": True}
        with yt_dlp.YoutubeDL(simple_opts) as ydl_simple:
            ydl_simple.download([url])
        return output_path
    
    finally:
        progress_bar.empty()
        progress_text.empty()


def process_video(
    video_input,
    idx,
    progress_manager,
    subtitle_ext,
    generate_format,
    output_language,          # ← NEW
    whisper_config,
    auto_font_size_enabled,
    manual_font_size,
    deepl_key,
    gemini_key,
):
    """Processes a single video: download (if URL), convert, transcribe,
    translate, generate subtitle content in memory."""
    video_start_time = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{idx:02}_{timestamp}"
    output_filename = f"{prefix}{subtitle_ext}"
    temp_wav_path = f"./{prefix}_temp.wav"
    downloaded_video_path = None
    audio_path_for_whisper = None
    video_path = None

    progress_manager.update(0, f"[{prefix}] 処理開始: {video_input}")
    download_status_placeholder = st.empty()

    try:
        # 1. Download or open local
        if is_valid_url(video_input):
            progress_manager.update(5, f"[{prefix}] URLから動画をダウンロード準備中...")
            video_path = download_video(video_input, prefix=f"{prefix}_")
            downloaded_video_path = video_path
            progress_manager.update(
                15,
                f"[{prefix}] ダウンロード完了: {os.path.basename(video_path)}",
            )
        elif check_local_file(video_input):
            video_path = video_input
            progress_manager.update(
                15,
                f"[{prefix}] ローカルファイルを使用: {os.path.basename(video_path)}",
            )
        else:
            st.error(f"[{prefix}] 入力が URL でも既存ファイルでもありません: {video_input}")
            return None

        # 2. Convert to WAV if necessary
        if not video_path.lower().endswith(".wav"):
            progress_manager.update(20, f"[{prefix}] 音声ファイルをWAV形式に変換中...")
            audio_path_for_whisper = convert_to_wav(video_path, temp_wav_path)
            if not audio_path_for_whisper:
                return None
            progress_manager.update(
                35,
                f"[{prefix}] WAV変換完了: {os.path.basename(audio_path_for_whisper)}",
            )
        else:
            audio_path_for_whisper = video_path
            progress_manager.update(
                35, f"[{prefix}] 入力はWAVファイルのため、変換をスキップ。"
            )

        # 3. Transcribe
        progress_manager.update(
            40,
            f"[{prefix}] Whisperモデル ({whisper_config['model_size']}) 読み込み＆文字起こし中...",
        )
        segments, info = transcribe_with_faster_whisper(
            audio_path_for_whisper,
            whisper_config["model_size"],
            "cpu",
            "int8",
            whisper_config["beam_size"],
        )
        if segments is None:
            return None
        progress_manager.update(
            80,
            f"[{prefix}] 文字起こし完了。言語: {info.language} ({info.language_probability:.2f})",
        )
        # 4. Translate (if target language differs)
        target_lang_ui = output_language
        source_lang_whisper = info.language

        if (
            target_lang_ui
            and target_lang_ui not in ["", source_lang_whisper]
        ):
            progress_manager.update(
                82,
                f"[{prefix}] {source_lang_whisper} -> {target_lang_ui} 翻訳中...",
            )
            translated_segments = []
            for seg_idx, seg in enumerate(segments, 1):
                try:
                    text_translated, err = translate_text_deepl(
                        seg.text,
                        source_lang_whisper,
                        target_lang_ui,
                        deepl_api_key=deepl_key,
                    )
                    if text_translated is None:
                        raise RuntimeError(err or "DeepL translation failed")
                except Exception:
                    # Fallback to Gemini
                    text_translated, _ = translate_text_gemini(
                        seg.text,
                        source_lang_whisper,
                        target_lang_ui,
                        gemini_api_key=gemini_key,
                    )
                # Update text
                try:
                    seg.text = text_translated
                except AttributeError:
                    seg = seg._replace(text=text_translated)  # namedtuple case
                translated_segments.append(seg)

                progress_manager.update(
                    82 + int(3 * seg_idx / len(segments)),
                    f"[{prefix}] 翻訳中... ({seg_idx}/{len(segments)})",
                )
            segments = translated_segments
            progress_manager.update(85, f"[{prefix}] 翻訳完了。")
        else:
            progress_manager.update(85, f"[{prefix}] 翻訳スキップ。")

        # 5. 字幕ファイルの生成と保存
        output_dir = Path("./generated_subs")
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / output_filename

        if generate_format.upper() == "SRT":
            _write_srt(segments, output_path)
        elif generate_format.upper() == "ASS":
            _write_ass(segments, output_path, manual_font_size)
        elif generate_format.upper() == "FCPXML":
            # FCPXML writer using fcpxml_utils
            xml_content = generate_fcpxml(segments, video_path, manual_font_size)
            if xml_content:
                with output_path.open("w", encoding="utf-8") as f:
                    f.write(xml_content)
            else:
                with output_path.open("w", encoding="utf-8") as f:
                    f.write('<?xml version="1.0"?><fcpxml></fcpxml>')
        else:
            # Unsupported format fallback
            with output_path.open("w", encoding="utf-8") as f:
                f.write("// 未対応フォーマット: ここに実装予定\n")

        # 5. 戻り値として生成したバイナリ/パスなどを返す
        return {
            "prefix": prefix,
            "segments": segments,
            "info": info,
            "output_filename": str(output_path),
            "video_path": video_path,
        }

    finally:
        # Cleanup
        # if downloaded_video_path and os.path.exists(downloaded_video_path):
        #     try:
        #         os.remove(downloaded_video_path)
        #     except OSError:
        #         pass
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except OSError:
                pass


def main_process(
    video_inputs,
    progress_manager,
    subtitle_ext,
    generate_format,
    output_language,          # ← NEW
    whisper_config,
    auto_font_size_enabled,
    manual_font_size,
    deepl_key,
    gemini_key,
):
    """Handles a list of video_inputs sequentially by calling process_video()."""
    results = []
    for idx, video_input in enumerate(video_inputs, start=1):
        res = process_video(
            video_input,
            idx,
            progress_manager,
            subtitle_ext,
            generate_format,
            output_language,          # ← PASS THROUGH
            whisper_config,
            auto_font_size_enabled,
            manual_font_size,
            deepl_key,
            gemini_key,
        )
        if res:
            results.append(res)
    return results
