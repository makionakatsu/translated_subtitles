// Editor state lives entirely client-side; the server is the persistence
// layer of last resort (debounced PATCH on idle). zundo wraps the slice we
// care about (`segments`, `selectedId`) so Cmd+Z / Cmd+Shift+Z can travel
// through the user's edit history.

import { create } from "zustand";
import { temporal } from "zundo";
import type { TemporalState } from "zundo";
import { useStore } from "zustand";
import type { Segment, SegmentEdit } from "@/lib/types";

interface EditorMeta {
  jobId: string | null;
  sourceLanguage: string | null;
  targetLanguage: string | null;
  width: number;
  height: number;
  videoUrl: string | null;
}

interface EditorState extends EditorMeta {
  segments: Segment[];
  selectedId: number | null;
  currentTime: number; // seconds, source of truth for sync
  dirty: Set<number>; // segment ids with unsaved edits
  setMeta: (meta: Partial<EditorMeta>) => void;
  hydrate: (segments: Segment[], meta: Partial<EditorMeta>) => void;
  setCurrentTime: (t: number) => void;
  select: (id: number | null) => void;
  patchSegment: (id: number, edit: SegmentEdit) => void;
  splitAtCaret: (id: number, caret: number) => void;
  mergeWithNext: (id: number) => void;
  insertAfter: (id: number) => void;
  deleteSegment: (id: number) => void;
  clearDirty: () => void;
}

export const useEditorStore = create<EditorState>()(
  temporal(
    (set) => ({
      jobId: null,
      sourceLanguage: null,
      targetLanguage: null,
      width: 1920,
      height: 1080,
      videoUrl: null,
      segments: [],
      selectedId: null,
      currentTime: 0,
      dirty: new Set<number>(),

      setMeta: (meta) => set((s) => ({ ...s, ...meta })),

      hydrate: (segments, meta) =>
        set((s) => ({
          ...s,
          ...meta,
          segments,
          dirty: new Set<number>(),
          selectedId: segments[0]?.id ?? null,
        })),

      setCurrentTime: (t) => set({ currentTime: t }),

      select: (id) => set({ selectedId: id }),

      patchSegment: (id, edit) =>
        set((s) => {
          const next = s.segments.map((seg) =>
            seg.id === id ? { ...seg, ...edit } : seg
          );
          const dirty = new Set(s.dirty);
          dirty.add(id);
          return { segments: next, dirty };
        }),

      splitAtCaret: (id, caret) =>
        set((s) => {
          const idx = s.segments.findIndex((x) => x.id === id);
          if (idx === -1) return s;
          const seg = s.segments[idx];
          const left = seg.text.slice(0, caret).trim();
          const right = seg.text.slice(caret).trim();
          if (!left || !right) return s;
          const dur = seg.end - seg.start;
          const ratio = caret / Math.max(1, seg.text.length);
          const split = seg.start + dur * ratio;
          const newId = Math.max(...s.segments.map((x) => x.id)) + 1;
          const left_seg: Segment = { ...seg, text: left, end: split };
          const right_seg: Segment = {
            ...seg,
            id: newId,
            text: right,
            start: split,
            end: seg.end,
          };
          const dirty = new Set(s.dirty);
          dirty.add(id);
          dirty.add(newId);
          return {
            segments: [
              ...s.segments.slice(0, idx),
              left_seg,
              right_seg,
              ...s.segments.slice(idx + 1),
            ],
            dirty,
            selectedId: newId,
          };
        }),

      mergeWithNext: (id) =>
        set((s) => {
          const idx = s.segments.findIndex((x) => x.id === id);
          if (idx === -1 || idx + 1 >= s.segments.length) return s;
          const a = s.segments[idx];
          const b = s.segments[idx + 1];
          const merged: Segment = {
            ...a,
            end: b.end,
            text: `${a.text.trim()} ${b.text.trim()}`.trim(),
          };
          const dirty = new Set(s.dirty);
          dirty.add(a.id);
          return {
            segments: [
              ...s.segments.slice(0, idx),
              merged,
              ...s.segments.slice(idx + 2),
            ],
            dirty,
            selectedId: a.id,
          };
        }),

      insertAfter: (id) =>
        set((s) => {
          const idx = s.segments.findIndex((x) => x.id === id);
          if (idx === -1) return s;
          const seg = s.segments[idx];
          const next = s.segments[idx + 1];
          const start = seg.end;
          const end = Math.min(seg.end + 1.5, next?.start ?? seg.end + 1.5);
          const newId = Math.max(...s.segments.map((x) => x.id)) + 1;
          const newSeg: Segment = {
            id: newId,
            start,
            end,
            text: "",
            original_text: null,
            words: [],
            speaker: seg.speaker,
            locked: false,
            avg_logprob: null,
            updated_at: new Date().toISOString(),
          };
          const dirty = new Set(s.dirty);
          dirty.add(newId);
          return {
            segments: [
              ...s.segments.slice(0, idx + 1),
              newSeg,
              ...s.segments.slice(idx + 1),
            ],
            dirty,
            selectedId: newId,
          };
        }),

      deleteSegment: (id) =>
        set((s) => {
          const idx = s.segments.findIndex((x) => x.id === id);
          if (idx === -1) return s;
          const remaining = s.segments.filter((x) => x.id !== id);
          const dirty = new Set(s.dirty);
          dirty.add(id);
          return {
            segments: remaining,
            dirty,
            selectedId: remaining[Math.min(idx, remaining.length - 1)]?.id ?? null,
          };
        }),

      clearDirty: () => set({ dirty: new Set<number>() }),
    }),
    {
      // Only the parts that matter for undo/redo travel through history.
      partialize: (s) => ({
        segments: s.segments,
        selectedId: s.selectedId,
      }),
      limit: 200,
    }
  )
);

// Hook to access the temporal store (history navigation).
export function useEditorHistory<T>(
  selector: (state: TemporalState<{ segments: Segment[]; selectedId: number | null }>) => T
): T {
  return useStore(useEditorStore.temporal, selector);
}
