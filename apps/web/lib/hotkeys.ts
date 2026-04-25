// Tiny hotkey helper. The full Aegisub-style binding map lives at
// `useEditorHotkeys` in components/. This module only exposes the predicate
// utilities so the same modifier rules apply everywhere (palette, grid,
// inspector).

export type Modifiers = "mod" | "shift" | "alt";

export interface HotkeyEvent {
  key: string;
  mod: boolean; // Cmd on macOS, Ctrl elsewhere
  shift: boolean;
  alt: boolean;
}

export function fromKeyboardEvent(e: KeyboardEvent): HotkeyEvent {
  const isMac =
    typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  return {
    key: e.key.length === 1 ? e.key.toLowerCase() : e.key,
    mod: isMac ? e.metaKey : e.ctrlKey,
    shift: e.shiftKey,
    alt: e.altKey,
  };
}

// Skip if focus is on a content-editable / input / textarea — except for the
// few global keys (Cmd+Z etc) the caller passes via `globals`.
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  if (target.isContentEditable) return true;
  return false;
}
