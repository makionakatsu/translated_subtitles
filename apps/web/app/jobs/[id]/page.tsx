"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useEditorStore } from "@/stores/editor";
import { api, downloadUrl } from "@/lib/api";
import { fromKeyboardEvent, isTypingTarget } from "@/lib/hotkeys";
import { TopBar } from "@/components/TopBar";
import { VideoPane } from "@/components/VideoPane";
import { Waveform } from "@/components/Waveform";
import { SubtitleGrid } from "@/components/SubtitleGrid";
import { Inspector } from "@/components/Inspector";
import { JobDock } from "@/components/JobDock";

export default function EditorPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;

  const segments = useEditorStore((s) => s.segments);
  const dirty = useEditorStore((s) => s.dirty);
  const hydrate = useEditorStore((s) => s.hydrate);
  const clearDirty = useEditorStore((s) => s.clearDirty);

  const [error, setError] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  // The /api/jobs/:id/media endpoint streams whatever yt-dlp / the user's
  // local file lands on. The HTML5 video can fetch it directly.
  const videoUrl = `/api/jobs/${jobId}/media`;

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [segmentsResp, jobResp] = await Promise.all([
          api.getSegments(jobId),
          api.getJob(jobId),
        ]);
        if (cancelled) return;
        hydrate(segmentsResp.segments, {
          jobId,
          sourceLanguage: segmentsResp.source_language,
          targetLanguage: segmentsResp.target_language,
          width: segmentsResp.width,
          height: segmentsResp.height,
        });
        setOutputs(jobResp.outputs);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId, hydrate]);

  // ── Auto-save: PATCH dirty edits 800ms after the user stops typing ────────
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (dirty.size === 0) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      const editsArr = Array.from(dirty);
      const edits: Record<number, { text: string; start: number; end: number }> = {};
      for (const id of editsArr) {
        const seg = segments.find((s) => s.id === id);
        if (!seg) continue;
        edits[id] = { text: seg.text, start: seg.start, end: seg.end };
      }
      try {
        setSaving(true);
        await api.patchSegments(jobId, edits);
        clearDirty();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setSaving(false);
      }
    }, 800);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [dirty, segments, jobId, clearDirty]);

  // ── Hotkeys ──────────────────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const hk = fromKeyboardEvent(e);
      const typing = isTypingTarget(e.target);
      const store = useEditorStore.getState();

      // Globals: undo/redo work even while typing.
      if (hk.mod && hk.key === "z" && !hk.shift) {
        e.preventDefault();
        useEditorStore.temporal.getState().undo();
        return;
      }
      if (hk.mod && (hk.key === "y" || (hk.key === "z" && hk.shift))) {
        e.preventDefault();
        useEditorStore.temporal.getState().redo();
        return;
      }

      if (typing) return;

      const sel = store.selectedId;
      const idx = store.segments.findIndex((s) => s.id === sel);
      const seg = idx >= 0 ? store.segments[idx] : null;

      if (e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        const v = document.querySelector("video");
        if (v) (v.paused ? v.play() : v.pause());
        return;
      }
      if (e.key === "Enter" && seg) {
        e.preventDefault();
        const next = store.segments[idx + 1];
        if (next) {
          store.select(next.id);
          store.setCurrentTime(next.start);
        }
        return;
      }
      if (e.key === "ArrowDown" && seg) {
        e.preventDefault();
        const next = store.segments[idx + 1];
        if (next) store.select(next.id);
        return;
      }
      if (e.key === "ArrowUp" && seg) {
        e.preventDefault();
        const prev = store.segments[idx - 1];
        if (prev) store.select(prev.id);
        return;
      }
      if (e.key.toLowerCase() === "g" && seg) {
        e.preventDefault();
        store.patchSegment(seg.id, { start: store.currentTime });
        return;
      }
      if (e.key.toLowerCase() === "h" && seg) {
        e.preventDefault();
        store.patchSegment(seg.id, { end: store.currentTime });
        return;
      }
      if (e.key.toLowerCase() === "j") {
        e.preventDefault();
        store.setCurrentTime(Math.max(0, store.currentTime - 2));
        return;
      }
      if (e.key.toLowerCase() === "l") {
        e.preventDefault();
        store.setCurrentTime(store.currentTime + 2);
        return;
      }
      if (hk.mod && hk.key === "m" && seg) {
        e.preventDefault();
        store.mergeWithNext(seg.id);
        return;
      }
      if (hk.mod && hk.key === "i" && seg) {
        e.preventDefault();
        store.insertAfter(seg.id);
        return;
      }
      if (e.key === "Delete" && seg) {
        e.preventDefault();
        store.deleteSegment(seg.id);
        return;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── Manual save ──────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (dirty.size === 0) return;
    setSaving(true);
    try {
      const edits: Record<number, { text: string; start: number; end: number }> = {};
      for (const id of dirty) {
        const seg = segments.find((s) => s.id === id);
        if (!seg) continue;
        edits[id] = { text: seg.text, start: seg.start, end: seg.end };
      }
      await api.patchSegments(jobId, edits);
      clearDirty();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleRebuild = async () => {
    try {
      const fresh = await api.regenerateOutputs(jobId);
      setOutputs(fresh);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const formats = useMemo(() => Object.keys(outputs), [outputs]);

  return (
    <div className="flex flex-col h-dvh">
      <TopBar
        saving={saving}
        onSave={handleSave}
        onExportRebuild={handleRebuild}
        formats={formats}
      />

      {error ? (
        <div className="bg-danger/10 text-danger text-xs px-4 py-2 border-b border-danger/30">
          {error}
        </div>
      ) : null}

      <div className="grid flex-1 min-h-0 grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_320px]">
        <VideoPane src={videoUrl} className="border-r border-white/5" />
        <SubtitleGrid className="border-r border-white/5" />
        <Inspector className="border-l border-white/5" />
      </div>
      <Waveform audioUrl={videoUrl} className="h-32 border-t border-white/10" />

      <JobDock />
    </div>
  );
}
