"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { OutputFormat } from "@/lib/types";

const MODELS = [
  { value: "large-v3-turbo", label: "Large v3 Turbo (推奨・速い)" },
  { value: "large-v3", label: "Large v3 (最高精度)" },
  { value: "medium", label: "Medium (中速・中精度)" },
  { value: "small", label: "Small (高速・低精度)" },
];

const TARGETS = [
  { value: "", label: "翻訳しない" },
  { value: "ja", label: "日本語" },
  { value: "en", label: "英語" },
  { value: "fr", label: "フランス語" },
  { value: "de", label: "ドイツ語" },
  { value: "es", label: "スペイン語" },
];

const ALL_FORMATS: OutputFormat[] = ["srt", "ass", "fcpxml"];

export function NewJobForm() {
  const [source, setSource] = useState("");
  const [model, setModel] = useState("large-v3-turbo");
  const [target, setTarget] = useState("ja");
  const [formats, setFormats] = useState<OutputFormat[]>(["srt", "ass"]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  function toggleFormat(fmt: OutputFormat) {
    setFormats((prev) =>
      prev.includes(fmt) ? prev.filter((x) => x !== fmt) : [...prev, fmt]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!source.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJob({
        source: source.trim(),
        target_lang: target || null,
        formats,
        model,
      });
      setCreated(job.id);
      setSource("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-xl border border-white/10 bg-white/5 p-5"
    >
      <div className="space-y-1.5">
        <label className="text-xs text-muted">URL またはローカルファイルのパス</label>
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=…  または  /Users/me/clip.mp4"
          className="w-full bg-white/5 px-3 py-2 rounded text-sm focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs text-muted">Whisper モデル</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full bg-white/5 px-3 py-2 rounded text-sm"
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-muted">出力言語</label>
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="w-full bg-white/5 px-3 py-2 rounded text-sm"
          >
            {TARGETS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs text-muted">出力フォーマット</label>
        <div className="flex gap-1.5">
          {ALL_FORMATS.map((fmt) => {
            const active = formats.includes(fmt);
            return (
              <button
                key={fmt}
                type="button"
                onClick={() => toggleFormat(fmt)}
                className={`px-3 py-1.5 rounded text-xs uppercase tracking-wider ${
                  active ? "bg-accent text-white" : "bg-white/5 text-muted"
                }`}
              >
                {fmt}
              </button>
            );
          })}
        </div>
      </div>

      {error ? <div className="text-xs text-danger">{error}</div> : null}
      {created ? (
        <div className="text-xs text-emerald-400">
          ジョブ {created} を作成しました。下の Dock で進捗を確認してください。
        </div>
      ) : null}

      <button
        disabled={submitting || !source.trim() || formats.length === 0}
        className="w-full px-4 py-2 rounded bg-accent text-white font-medium text-sm disabled:opacity-50"
      >
        {submitting ? "送信中…" : "字幕生成を開始"}
      </button>
    </form>
  );
}
