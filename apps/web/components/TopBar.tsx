"use client";

import Link from "next/link";
import { useEditorStore } from "@/stores/editor";
import { cn } from "@/lib/cn";

interface Props {
  saving: boolean;
  onSave: () => void;
  onExportRebuild: () => void;
  onBurn: () => void;
  formats: string[];
  burning?: boolean;
  className?: string;
}

export function TopBar({
  saving,
  onSave,
  onExportRebuild,
  onBurn,
  formats,
  burning,
  className,
}: Props) {
  const dirty = useEditorStore((s) => s.dirty);
  const jobId = useEditorStore((s) => s.jobId);
  const dirtyCount = dirty.size;

  return (
    <header
      className={cn(
        "flex items-center justify-between border-b border-white/10 px-4 py-2",
        className
      )}
    >
      <div className="flex items-center gap-3">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          字幕制作スイート
        </Link>
        {jobId ? (
          <span className="text-xs text-muted font-mono">{jobId}</span>
        ) : null}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-xs text-muted">
          {saving
            ? "保存中…"
            : dirtyCount === 0
              ? "保存済み"
              : `未保存 ${dirtyCount} 件`}
        </span>
        <button
          onClick={onSave}
          disabled={dirtyCount === 0 || saving}
          className="px-3 py-1 rounded bg-white/10 hover:bg-white/20 disabled:opacity-50 text-xs"
        >
          保存
        </button>
        <button
          onClick={onExportRebuild}
          className="px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-xs"
        >
          書き出し再生成
        </button>
        <button
          onClick={onBurn}
          disabled={burning}
          className="px-3 py-1 rounded bg-accent text-white text-xs font-medium disabled:opacity-50"
        >
          {burning ? "焼き込み中…" : "焼き込み"}
        </button>
        {formats.map((fmt) => (
          <a
            key={fmt}
            href={jobId ? `/api/jobs/${jobId}/outputs/${fmt}` : "#"}
            className="px-3 py-1 rounded bg-white/5 hover:bg-white/10 text-xs uppercase tracking-wider"
          >
            {fmt}
          </a>
        ))}
      </div>
    </header>
  );
}
