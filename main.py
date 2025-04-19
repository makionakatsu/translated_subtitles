"""
Streamlit front‑end for “字幕生成＆焼き込みくん”.
UI のみを保持し、処理ロジックは utils.processing に委譲します。
"""

# ── Imports ──────────────────────────────────────────────────────────
import os
import re
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

from utils.processing import (
    is_valid_url,
    check_local_file,
    download_video,
    process_video,
    main_process,
)
from utils.burn_utils import burn_subtitles
from utils.video_utils import get_video_resolution

# ── Initial Setup ────────────────────────────────────────────────────
st.set_page_config(page_title="一撃！字幕生成くん", page_icon="🎬", layout="wide")
load_dotenv()

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Helper UI class ─────────────────────────────────────────────────
class ProgressManager:
    """Simple wrapper around Streamlit progress UI."""
    def __init__(self):
        self.bar = st.progress(0)
        self.text = st.empty()

    def update(self, pct: float, msg: str):
        self.bar.progress(int(max(0, min(100, pct))))
        self.text.text(msg)

    def complete(self, msg: str = "完了！"):
        self.update(100, msg)


# ── API keys ─────────────────────────────────────────────────────────
st.header("1. API キー")
colk1, colk2 = st.columns(2)
with colk1:
    deepl_key = st.text_input("DeepL API Key", type="password")
with colk2:
    gemini_key = st.text_input("Gemini API Key", type="password")

# ── Session State ────────────────────────────────────────────────────
if "generated_subtitles" not in st.session_state:
    st.session_state.generated_subtitles = []  # List[Tuple(filename, segments, info)]
if "generated_pairs" not in st.session_state:
    st.session_state.generated_pairs = []      # List[dict(video, subtitle)]

# ── UI Tabs ──────────────────────────────────────────────────────────
tab_generate, tab_burn = st.tabs(["🎤 字幕ファイル作成", "🔥 字幕焼き込み"])

# ─────────────────────────────────────────────────────────────────────
# Tab 1 – Subtitle Generation
# ─────────────────────────────────────────────────────────────────────
with tab_generate:
    st.header("2. 入力ファイル／URL")

    # URL input
    url_block = st.text_area(
        "動画 URL（1 行に 1 つ）",
        placeholder="https://www.youtube.com/watch?…",
        height=100,
    )
    urls = [u.strip() for u in url_block.splitlines() if is_valid_url(u.strip())]

    # File uploader
    uploads = st.file_uploader(
        "またはローカル動画/音声ファイルを選択",
        type=["mp4", "mov", "mkv", "avi", "wav", "mp3", "m4a"],
        accept_multiple_files=True,
    )
    uploaded_paths = []
    if uploads:
        upload_dir = Path("./uploads")
        upload_dir.mkdir(exist_ok=True)
        for up in uploads:
            safe_name = re.sub(r"[\\/*?\"<>|:]", "_", up.name)
            dest = upload_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}"
            dest.write_bytes(up.getbuffer())
            uploaded_paths.append(str(dest))

    video_inputs = urls + uploaded_paths
    # ユーザー指定の左右余白率（％）
    margin_pct = st.slider("左右余白率 (%)", 0, 20, 2)
    # Determine default font size based on video width and margin_pct
    default_font_size = 50
    if video_inputs:
        first = video_inputs[0]
        try:
            if os.path.isfile(first):
                w, _ = get_video_resolution(first)
                left = int(w * margin_pct / 100)
                right = left
                available = w - left - right
                default_font_size = max(10, min(120, int(available * 0.05)))
        except Exception:
            default_font_size = 50

    st.header("3. 出力設定")
    col1, col2 = st.columns(2)

    with col1:
        format_choice = st.selectbox(
            "字幕形式",
            ["SRT", "ASS", "FCPXML"],
            index=0,
        )
        subtitle_ext = { "SRT": ".srt", "ASS": ".ass", "FCPXML": ".fcpxml" }[format_choice]

    with col2:
        whisper_size = st.selectbox("Whisper 精度", ["medium", "large"], index=0)
        whisper_cfg = { "model_size": whisper_size, "beam_size": 5 }

    # Font size option
    auto_font = st.checkbox("フォントサイズ自動", value=True)
    manual_font = st.slider(
        "フォントサイズ（手動）",
        10,
        120,
        default_font_size,
        disabled=auto_font,
    )

    # Output language
    output_language = st.selectbox(
        "出力言語",
        ["ja", "en", "fr", "de"],
        index=0,
    )

    # Run button
    st.markdown("---")
    if st.button("字幕生成開始", disabled=not video_inputs):
        prog = ProgressManager()
        results = main_process(
            video_inputs,
            prog,
            subtitle_ext,
            format_choice,
            output_language,
            whisper_cfg,
            auto_font,
            manual_font,
            deepl_key,
            gemini_key,
        )
        prog.complete("完了！")

        if results:
            st.success("字幕生成が完了しました。")
            st.session_state.generated_subtitles = [
                (res["output_filename"], res["segments"], res["info"]) for res in results
            ]
            # Store video–subtitle pairs
            for idx, res in enumerate(results):
                st.session_state.generated_pairs.append(
                    {
                        "video": res.get("video_path") or video_inputs[idx],
                        "subtitle": res["output_filename"],
                    }
                )

            # Download buttons
            for res in results:
                file_path = Path(res["output_filename"])
                mime = (
                    "application/xml"
                    if file_path.suffix.lower() == ".fcpxml"
                    else "text/plain"
                )
                col = st.columns(2)[0]
                with file_path.open("rb") as f:
                    col.download_button(
                        label=f"ダウンロード: {file_path.name}",
                        data=f.read(),
                        file_name=file_path.name,
                        mime=mime,
                    )

# ─────────────────────────────────────────────────────────────────────
# Tab 2 – Burn Subtitles
# ─────────────────────────────────────────────────────────────────────
with tab_burn:
    st.header("字幕焼き込み")

    DEFAULT = "▼ 生成済みペアを選択 ▼"
    pair_options = [DEFAULT] + [
        f"{Path(p['video']).name if p['video'] else 'URL'} → {Path(p['subtitle']).name}"
        for p in st.session_state.generated_pairs
    ]
    pair_choice = st.selectbox("生成済みの動画＋字幕ペアを使用", pair_options)

    video_file = None
    subtitle_file = None

    if pair_choice != DEFAULT:
        sel_idx = pair_options.index(pair_choice) - 1
        pair = st.session_state.generated_pairs[sel_idx]
        subtitle_path_selected = pair["subtitle"]

        temp_dir = Path("./burn_temp")
        temp_dir.mkdir(exist_ok=True)

        # Prefer existing local file; download only if missing
        candidate = pair["video"]
        if os.path.exists(str(candidate)):
            video_path_selected = candidate
        elif is_valid_url(candidate):
            st.info("URL から動画をダウンロード中…")
            video_path_selected = download_video(
                candidate,
                output_dir=str(temp_dir),
                prefix="burn_",
            )
        else:
            video_path_selected = candidate

        st.info(f"選択中: {video_path_selected} + {subtitle_path_selected}")
    else:
        video_file = st.file_uploader("動画ファイル", type=["mp4", "mov", "mkv", "avi"])
        subtitle_file = st.file_uploader("字幕ファイル", type=["srt", "ass"])

    burn_font_size = st.number_input(
        "フォントサイズ",
        10,
        120,
        default_font_size,
    )

    if st.button(
        "焼き込み開始",
        disabled=(
            pair_choice == DEFAULT and not (video_file and subtitle_file)
        ),
    ):
        with st.spinner("焼き込み中…"):
            temp_dir = Path("./burn_temp")
            temp_dir.mkdir(exist_ok=True)

            if pair_choice != DEFAULT:
                video_path = Path(video_path_selected)
                subtitle_path = Path(subtitle_path_selected)
            else:
                video_path = temp_dir / f"video_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{video_file.name}"
                subtitle_path = temp_dir / f"subs_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{subtitle_file.name}"
                video_path.write_bytes(video_file.getbuffer())
                subtitle_path.write_bytes(subtitle_file.getbuffer())

            try:
                output_path = burn_subtitles(
                    video_path,
                    subtitle_path,
                    burn_font_size,
                    temp_dir,
                )
                with output_path.open("rb") as f_out:
                    st.success("焼き込み完了！")
                    st.download_button(
                        label=f"ダウンロード: {output_path.name}",
                        data=f_out.read(),
                        file_name=output_path.name,
                        mime="video/mp4",
                    )
            except Exception as e:
                st.error("焼き込み失敗")
                st.text(str(e))