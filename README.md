# Local Caption MVP

Apple Silicon Macを第一ターゲットにした、ローカル動画向けの字幕生成・翻訳・編集・書き出しツールです。

## 起動

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

ブラウザで `http://127.0.0.1:8000` を開きます。

## 現在の主経路

1. URL、ローカル絶対パス、またはファイル選択で動画を取り込む
2. `字幕を生成` でASRを実行する
3. 入力言語と翻訳先が異なる場合だけGemini翻訳を続けて実行する
4. 動画プレビューと字幕表で確認・編集する
5. ASS/SRT/VTT/二言語ASS、または焼き込みMP4を書き出す

## ASR

- 既定は `auto` です。
- Apple Silicon macOSで `mlx-whisper` が使える場合はMLXを選びます。
- MLXが使えない環境では `faster-whisper` にfallbackします。

プリセット:

- `fast`: `mlx-community/whisper-small-mlx`
- `balanced`: `mlx-community/whisper-medium-mlx`
- `quality`: `mlx-community/whisper-large-v3-mlx`

モデルは以下の環境変数で上書きできます。

```bash
MLX_WHISPER_MODEL_FAST=...
MLX_WHISPER_MODEL_BALANCED=...
MLX_WHISPER_MODEL_QUALITY=...
```

## 翻訳

- 既定の翻訳先は日本語です。
- Gemini APIキーは `GEMINI_API_KEY`、またはUIの保存操作で設定します。
- UI保存時は可能ならmacOS Keychain、使えない場合はローカル設定ファイルに保存します。
- `project.json` にはAPIキーや全文promptを保存しません。
- Gemini失敗時はArgos Translate、さらに失敗した場合は元文維持とwarningにfallbackします。

## Preflight

UI右側の「システム状態」は自動実行されます。手動確認する場合:

```bash
curl -s http://127.0.0.1:8000/api/preflight | python3 -m json.tool
```

確認対象:

- Python実行ファイルとバージョン
- Apple Silicon判定
- `ffmpeg` / `ffprobe`
- `mlx` / `mlx_whisper`
- ASRエンジン選択結果
- Gemini APIキー
- subtitle render filter
- 壊れた `.venv`

## テスト

```bash
python3 -m compileall main.py app tests
python3 -m pytest -q
```

実動画のMLX ASRはモデルダウンロードを伴うため、自動テストではbackend選択とfallbackをフェイクで検証しています。
