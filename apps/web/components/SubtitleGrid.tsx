"use client";

import { useMemo, useRef, useEffect } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEditorStore } from "@/stores/editor";
import {
  charsPerSecond,
  cpsSeverity,
  formatTimecode,
  severityClasses,
  thresholdsFor,
} from "@/lib/cps";
import { cn } from "@/lib/cn";

// A virtualised editable list. We deliberately avoid TanStack Table here
// because the row interaction model is bespoke (split, merge, drag-resize via
// the waveform) and the table abstraction adds friction without saving rows.

export function SubtitleGrid({ className }: { className?: string }) {
  const segments = useEditorStore((s) => s.segments);
  const selectedId = useEditorStore((s) => s.selectedId);
  const targetLang = useEditorStore((s) => s.targetLanguage);
  const select = useEditorStore((s) => s.select);
  const patch = useEditorStore((s) => s.patchSegment);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const dirty = useEditorStore((s) => s.dirty);

  const thresholds = thresholdsFor(targetLang ?? "en");
  const parentRef = useRef<HTMLDivElement | null>(null);

  const rowVirtualizer = useVirtualizer({
    count: segments.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 76,
    overscan: 8,
  });

  // Auto-scroll to selection when it changes externally (e.g. clicked on the
  // waveform).
  useEffect(() => {
    if (selectedId == null) return;
    const idx = segments.findIndex((s) => s.id === selectedId);
    if (idx >= 0) rowVirtualizer.scrollToIndex(idx, { align: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const items = useMemo(() => rowVirtualizer.getVirtualItems(), [rowVirtualizer]);

  return (
    <div ref={parentRef} className={cn("h-full overflow-auto", className)}>
      <div
        className="relative w-full"
        style={{ height: rowVirtualizer.getTotalSize() }}
      >
        {items.map((virtual) => {
          const seg = segments[virtual.index];
          const dur = Math.max(0.001, seg.end - seg.start);
          const cps = charsPerSecond(seg.text, dur);
          const sev = cpsSeverity(cps, thresholds);
          const sevCls = severityClasses(sev);
          const isSelected = selectedId === seg.id;
          const isDirty = dirty.has(seg.id);
          // Confidence heatmap: avg_logprob is approx -0.0 (great) to -1.0 (poor)
          const confAlpha =
            seg.avg_logprob == null
              ? 0
              : Math.max(0, Math.min(0.4, -seg.avg_logprob * 0.4));
          return (
            <div
              key={seg.id}
              data-segid={seg.id}
              className={cn(
                "absolute inset-x-0 grid grid-cols-[80px_80px_1fr_64px] gap-3 px-3 py-2 border-b border-white/5 cursor-pointer text-sm",
                isSelected ? "bg-accent/10" : "hover:bg-white/5"
              )}
              style={{
                top: virtual.start,
                height: virtual.size,
                backgroundColor: isSelected
                  ? undefined
                  : `rgba(255,180,80,${confAlpha})`,
              }}
              onClick={() => {
                select(seg.id);
                setCurrentTime(seg.start);
              }}
            >
              <span className="text-xs text-muted self-center">
                {formatTimecode(seg.start)}
              </span>
              <span className="text-xs text-muted self-center">
                {formatTimecode(seg.end)}
              </span>
              <textarea
                value={seg.text}
                onChange={(e) => patch(seg.id, { text: e.target.value })}
                onFocus={() => select(seg.id)}
                rows={2}
                className="bg-transparent resize-none focus:outline-none focus:ring-1 focus:ring-accent/40 rounded-sm px-1 leading-snug"
              />
              <div className="flex items-center gap-1.5 self-center">
                <span className={cn("h-2 w-2 rounded-full", sevCls.dot)} />
                <span className={cn("text-xs tabular-nums", sevCls.text)}>
                  {cps.toFixed(1)}
                </span>
                {isDirty ? (
                  <span className="text-[10px] text-amber-400" title="未保存">
                    •
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
