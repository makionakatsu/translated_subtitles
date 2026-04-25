"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useEditorStore } from "@/stores/editor";
import { cn } from "@/lib/cn";

interface Props {
  src: string | null;
  className?: string;
  /** Optional render-prop receiving the underlying <video> element so an
   *  overlay (e.g. JASSUB) can mount on top of it. */
  overlay?: (video: HTMLVideoElement | null) => ReactNode;
}

// HTML5 video pane. Phase 4 layers a JASSUB canvas via the `overlay` prop. The
// editor store is the source of truth for `currentTime` — this component
// listens to `timeupdate` to write back, and applies large external seeks.
export function VideoPane({ src, className, overlay }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const [, force] = useState(0);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const targetTime = useEditorStore((s) => s.currentTime);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (Math.abs(video.currentTime - targetTime) > 0.05) {
      video.currentTime = targetTime;
    }
  }, [targetTime]);

  return (
    <div className={cn("relative bg-black/95 flex items-center justify-center", className)}>
      {src ? (
        <div className="relative">
          <video
            ref={(el) => {
              ref.current = el;
              // Force one re-render so the overlay render-prop receives the
              // mounted element instead of null.
              force((n) => n + 1);
            }}
            src={src}
            controls
            className="max-h-full max-w-full"
            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          />
          {overlay ? overlay(ref.current) : null}
        </div>
      ) : (
        <div className="text-muted text-sm">動画ソースがまだありません</div>
      )}
    </div>
  );
}
