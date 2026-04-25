# 字幕制作スイート (translated_subtitles)

AI subtitle generation, translation, and editing — Mac-first.

* **Backend** (`apps/api/`): FastAPI + mlx-whisper (Apple Silicon) / faster-whisper (CI fallback) + Gemini batch translation. SRT / ASS / FCPXML writers, ffmpeg burn-in, SSE progress streaming.
* **Frontend** (`apps/web/`): Next.js 14 (App Router) + Tailwind. The Aegisub-class three-pane editor (video + waveform + grid) lands in Phase 3; jassub-based ASS preview in Phase 4.

## Quick start

```bash
# Backend
uv sync --extra mac --extra dev          # use --extra cpu on Linux/CI
uv run uvicorn apps.api.main:app --reload --port 8000

# Frontend
cd apps/web
pnpm install
pnpm dev                                 # http://localhost:3000
```

Set `GEMINI_API_KEY` in the environment (or a `.env` at the repo root) to enable translation.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Start a transcribe/translate/write job. Body: `{source, target_lang?, formats[], model, ...}` |
| `GET` | `/api/jobs/{id}` | Job status |
| `GET` | `/api/jobs/{id}/outputs/{fmt}` | Download a generated file |
| `POST` | `/api/jobs/{id}/cancel` | Cancel a running job |
| `GET` | `/sse/jobs/{id}` | Stream `JobProgress` events as Server-Sent Events |
| `GET` | `/api/styles` | List bundled ASS styles |

## Tests

```bash
uv run pytest                 # full suite, snapshot pinned
uv run pytest --update-snapshots
uv run ruff check .
uv run mypy apps/api
```

## Roadmap

1. **P0** ✅ monorepo, CI, snapshot freeze
2. **P1** ✅ mlx-whisper backend, FasterWhisper CI fallback, hallucination tuning
3. **P2** ✅ Gemini-only batch translation with context window + glossary
4. **P3** Editor UI: video + wavesurfer waveform + TanStack Table grid + hotkeys + Undo/Redo
5. **P4** jassub WASM ASS preview + StyleForm + font upload
6. **P5** Burn-in / Export pipeline + JobDock UI
7. **P6** Tauri wrap for macOS bundle distribution
