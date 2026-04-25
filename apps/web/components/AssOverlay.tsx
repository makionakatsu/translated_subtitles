"use client";

import { useEffect, useRef, useState } from "react";
import { createJassub, type JassubHandle } from "@/lib/jassub/bridge";

interface Props {
  // The <video> element to overlay onto. Refs become available after mount
  // so this is a Ref to a HTMLVideoElement | null.
  videoEl: HTMLVideoElement | null;
  /** ASS document text. Re-rendered whenever this changes. */
  assContent: string;
}

// Lays a JASSUB-driven canvas over the supplied <video>. Resizes to match
// the video's bounding box and drives JASSUB's setTrack on every assContent
// update so the editor's preview stays in lockstep with the segments + style.
export function AssOverlay({ videoEl, assContent }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const handleRef = useRef<JassubHandle | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ── Mount / teardown ──────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    if (!videoEl || !canvasRef.current) return;
    (async () => {
      try {
        const handle = await createJassub({
          video: videoEl,
          canvas: canvasRef.current!,
          subContent: assContent || "[Script Info]\nScriptType: v4.00+\n",
        });
        if (cancelled) {
          handle.destroy();
          return;
        }
        handleRef.current = handle;
      } catch (e) {
        setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
      handleRef.current?.destroy();
      handleRef.current = null;
    };
  }, [videoEl]);

  // ── Live update on assContent change ──────────────────────────────────────
  useEffect(() => {
    handleRef.current?.setSubContent(
      assContent || "[Script Info]\nScriptType: v4.00+\n"
    );
  }, [assContent]);

  // ── Mirror video bounding box ─────────────────────────────────────────────
  useEffect(() => {
    if (!videoEl || !canvasRef.current) return;
    const ro = new ResizeObserver(() => {
      if (!videoEl || !canvasRef.current) return;
      canvasRef.current.style.width = `${videoEl.clientWidth}px`;
      canvasRef.current.style.height = `${videoEl.clientHeight}px`;
      handleRef.current?.setVideoSize(
        videoEl.clientWidth || 1920,
        videoEl.clientHeight || 1080
      );
    });
    ro.observe(videoEl);
    return () => ro.disconnect();
  }, [videoEl]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 pointer-events-none"
        aria-hidden
      />
      {error ? (
        <div className="absolute bottom-1 left-1 text-xs bg-danger/30 text-danger px-2 py-0.5 rounded">
          ASS overlay: {error}
        </div>
      ) : null}
    </>
  );
}
