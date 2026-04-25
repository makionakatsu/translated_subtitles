# Web (Next.js 14, App Router)

Frontend for the subtitle suite. Browser-first, designed to be statically exported and wrapped in Tauri in Phase 6.

```bash
pnpm install      # or npm install
pnpm dev          # http://localhost:3000 (proxies /api -> http://localhost:8000)
```

The development server proxies `/api`, `/sse`, and `/ws` to the FastAPI backend on port 8000 — see `next.config.mjs`.
