"use client";

import { useState } from "react";
import { useEditorStore } from "@/stores/editor";
import {
  charsPerSecond,
  cpsSeverity,
  formatTimecode,
  severityClasses,
  thresholdsFor,
} from "@/lib/cps";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

export function Inspector({ className }: { className?: string }) {
  const segments = useEditorStore((s) => s.segments);
  const selectedId = useEditorStore((s) => s.selectedId);
  const jobId = useEditorStore((s) => s.jobId);
  const targetLang = useEditorStore((s) => s.targetLanguage);
  const sourceLang = useEditorStore((s) => s.sourceLanguage);
  const patch = useEditorStore((s) => s.patchSegment);

  const seg = segments.find((s) => s.id === selectedId);
  const thresholds = thresholdsFor(targetLang ?? "en");

  const [candidates, setCandidates] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!seg) {
    return (
      <aside className={cn("p-4 text-sm text-muted", className)}>
        セグメントを選択してください
      </aside>
    );
  }

  const dur = Math.max(0.001, seg.end - seg.start);
  const cps = charsPerSecond(seg.text, dur);
  const sev = cpsSeverity(cps, thresholds);
  const sevCls = severityClasses(sev);

  async function handleRetranslate() {
    if (!jobId || !seg) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.retranslate(jobId, seg.id, 3);
      setCandidates(result.candidates);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <aside className={cn("flex flex-col gap-4 p-4 overflow-auto text-sm", className)}>
      <header className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-muted">Segment {seg.id}</h2>
        <span className={cn("text-xs px-2 py-0.5 rounded-full", sevCls.bg, sevCls.text)}>
          {cps.toFixed(1)} cps
        </span>
      </header>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">タイムコード</label>
        <div className="flex items-center gap-2 tabular-nums">
          <input
            value={formatTimecode(seg.start)}
            onChange={(e) =>
              patch(seg.id, { start: parseTimecode(e.target.value) ?? seg.start })
            }
            className="bg-white/5 px-2 py-1 rounded font-mono w-32"
          />
          <span className="text-muted">→</span>
          <input
            value={formatTimecode(seg.end)}
            onChange={(e) =>
              patch(seg.id, { end: parseTimecode(e.target.value) ?? seg.end })
            }
            className="bg-white/5 px-2 py-1 rounded font-mono w-32"
          />
          <span className="text-xs text-muted">{dur.toFixed(2)}s</span>
        </div>
      </section>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">原文</label>
        <div className="text-xs text-muted/80 px-2 py-1 bg-white/5 rounded">
          {seg.original_text ?? "—"}
        </div>
      </section>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">翻訳 / 字幕</label>
        <textarea
          value={seg.text}
          onChange={(e) => patch(seg.id, { text: e.target.value })}
          rows={4}
          className="w-full bg-white/5 px-2 py-1.5 rounded resize-none focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
      </section>

      <section className="space-y-2">
        <button
          onClick={handleRetranslate}
          disabled={loading}
          className="w-full px-3 py-2 rounded bg-accent text-white text-sm font-medium disabled:opacity-50"
        >
          {loading ? "AI に問い合わせ中…" : "AI で再翻訳 (3案)"}
        </button>
        {error ? <div className="text-xs text-danger">{error}</div> : null}
        {candidates ? (
          <ul className="space-y-1">
            {candidates.map((c, i) => (
              <li key={i}>
                <button
                  onClick={() => patch(seg.id, { text: c })}
                  className="w-full text-left px-2 py-1.5 rounded bg-white/5 hover:bg-white/10"
                >
                  {c}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {sourceLang ? (
        <footer className="text-xs text-muted">
          {sourceLang} → {targetLang ?? "—"}
          {seg.avg_logprob != null
            ? ` · 信頼度 ${(1 + seg.avg_logprob).toFixed(2)}`
            : ""}
        </footer>
      ) : null}
    </aside>
  );
}

function parseTimecode(text: string): number | null {
  const m = text.match(/^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/);
  if (!m) return null;
  const [, h, mi, s] = m;
  return Number(h) * 3600 + Number(mi) * 60 + Number(s);
}
