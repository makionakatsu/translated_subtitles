"use client";

import { useEffect, useRef } from "react";
import { useEditorStore } from "@/stores/editor";
import { cn } from "@/lib/cn";

interface Props {
  src: string | null;
  className?: string;
}

// HTML5 video pane. Phase 4 layers a JASSUB canvas over this for live ASS
// rendering. The store is the source of truth for currentTime — this component
// listens to `timeupdate` and writes back, but only when the user is driving
// playback (otherwise we'd loop with the grid double-click handler).
export function VideoPane({ src, className }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const targetTime = useEditorStore((s) => s.currentTime);

  // External seeks (grid clicks, hotkeys) — drive the <video> programmatically
  // when the delta is large enough to matter.
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
        <video
          ref={ref}
          src={src}
          controls
          className="max-h-full max-w-full"
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        />
      ) : (
        <div className="text-muted text-sm">動画ソースがまだありません</div>
      )}
    </div>
  );
}
