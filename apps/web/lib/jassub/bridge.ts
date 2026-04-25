// Thin wrapper around the JASSUB renderer.
//
// JASSUB compiles libass to WASM and renders SSA/ASS subtitles onto a canvas
// that we overlay on the <video>. The wasm + worker live in /public/jassub
// (copied by scripts/copy-jassub.mjs at install / dev / build time).
//
// We intentionally avoid the *.es.js direct import because Next.js' SWC
// minifier mangles a few of jassub's worker self-references; instead we
// dynamic-import inside the browser only.

import type { default as JassubType } from "jassub";

export interface JassubInit {
  video: HTMLVideoElement;
  canvas: HTMLCanvasElement;
  subContent: string;
  fonts?: string[];
}

export interface JassubHandle {
  setSubContent: (assText: string) => void;
  setVideoSize: (width: number, height: number) => void;
  /** ``font`` may be a URL string or a Uint8Array binary blob. JASSUB infers
   *  the family from the file's name table. */
  addFont: (font: string | Uint8Array) => void;
  destroy: () => void;
}

let _ctor: typeof JassubType | null = null;

async function loadConstructor(): Promise<typeof JassubType> {
  if (_ctor) return _ctor;
  const mod = await import("jassub");
  _ctor = mod.default;
  return _ctor;
}

export async function createJassub(opts: JassubInit): Promise<JassubHandle> {
  const Jassub = await loadConstructor();
  const instance = new Jassub({
    video: opts.video,
    canvas: opts.canvas,
    subContent: opts.subContent,
    fonts: opts.fonts ?? [],
    workerUrl: "/jassub/jassub-worker.js",
    wasmUrl: "/jassub/jassub-worker.wasm",
    modernWasmUrl: "/jassub/jassub-worker-modern.wasm",
    fallbackFont: "/jassub/default.woff2",
    asyncRender: true,
    offscreenRender: typeof OffscreenCanvas !== "undefined",
  });

  return {
    setSubContent: (text) => {
      // setTrack reloads the entire ASS document — that's what we want for
      // edits, since segments and styles can both change.
      instance.setTrack(text);
    },
    setVideoSize: (width, height) => {
      instance.resize(width, height);
    },
    addFont: (font) => {
      instance.addFont(font);
    },
    destroy: () => {
      instance.destroy();
    },
  };
}
