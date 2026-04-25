"use client";

import { useEffect, useRef, useState } from "react";
import { useEditorStore } from "@/stores/editor";
import { cn } from "@/lib/cn";

interface Props {
  audioUrl: string | null;
  className?: string;
}

// Wavesurfer is heavy and ESM-only; we lazy-load it so SSR + first paint stay
// snappy. Regions plugin is loaded once via `RegionsPlugin.create()` and then
// kept in sync with the editor segments. The cursor rides ``currentTime``.
export function Waveform({ audioUrl, className }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<unknown>(null);
  const regionsRef = useRef<unknown>(null);
  const [ready, setReady] = useState(false);

  const segments = useEditorStore((s) => s.segments);
  const currentTime = useEditorStore((s) => s.currentTime);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const select = useEditorStore((s) => s.select);
  const patch = useEditorStore((s) => s.patchSegment);

  // ── Lazy boot ─────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    if (!audioUrl || !containerRef.current) return;
    (async () => {
      const [{ default: WaveSurfer }, { default: RegionsPlugin }] = await Promise.all([
        import("wavesurfer.js"),
        import("wavesurfer.js/dist/plugins/regions.esm.js"),
      ]);
      if (cancelled || !containerRef.current) return;
      const regions = (RegionsPlugin as unknown as { create: () => unknown }).create();
      const ws = (WaveSurfer as unknown as {
        create: (opts: Record<string, unknown>) => {
          on: (e: string, cb: (...args: unknown[]) => void) => void;
          setTime: (t: number) => void;
          getCurrentTime: () => number;
          destroy: () => void;
        };
      }).create({
        container: containerRef.current,
        waveColor: "rgba(120,120,140,0.6)",
        progressColor: "rgba(80,160,255,0.8)",
        cursorColor: "rgba(255,255,255,0.9)",
        height: 96,
        url: audioUrl,
        plugins: [regions],
      });
      wsRef.current = ws;
      regionsRef.current = regions;
      ws.on("ready", () => setReady(true));
      ws.on("seeking", () => {
        const t = ws.getCurrentTime();
        setCurrentTime(t);
      });
    })();
    return () => {
      cancelled = true;
      const ws = wsRef.current as { destroy?: () => void } | null;
      ws?.destroy?.();
      wsRef.current = null;
      regionsRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  // ── Mirror segments → regions ─────────────────────────────────────────────
  useEffect(() => {
    if (!ready) return;
    const regions = regionsRef.current as
      | {
          clearRegions: () => void;
          addRegion: (opts: Record<string, unknown>) => {
            on: (e: string, cb: (...args: unknown[]) => void) => void;
          };
        }
      | null;
    if (!regions) return;
    regions.clearRegions();
    for (const seg of segments) {
      const region = regions.addRegion({
        id: String(seg.id),
        start: seg.start,
        end: seg.end,
        drag: true,
        resize: true,
        color: "rgba(80,160,255,0.18)",
      });
      region.on("click", () => select(seg.id));
      region.on("update-end", (...args: unknown[]) => {
        const r = args[0] as { start: number; end: number };
        patch(seg.id, { start: r.start, end: r.end });
      });
    }
  }, [segments, ready, patch, select]);

  // ── Mirror currentTime → cursor ───────────────────────────────────────────
  useEffect(() => {
    const ws = wsRef.current as { setTime?: (t: number) => void; getCurrentTime?: () => number } | null;
    if (!ws?.setTime || !ws?.getCurrentTime) return;
    if (Math.abs(ws.getCurrentTime() - currentTime) > 0.05) {
      ws.setTime(currentTime);
    }
  }, [currentTime]);

  return (
    <div className={cn("relative w-full bg-black/80", className)}>
      <div ref={containerRef} className="w-full" />
      {!audioUrl ? (
        <div className="absolute inset-0 grid place-items-center text-xs text-muted">
          オーディオが利用可能になると波形が表示されます
        </div>
      ) : !ready ? (
        <div className="absolute inset-0 grid place-items-center text-xs text-muted">
          波形を読み込み中…
        </div>
      ) : null}
    </div>
  );
}
