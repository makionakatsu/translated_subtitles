"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

interface Props {
  jobId: string;
  onChange: () => void;
  className?: string;
}

interface StyleResponse {
  style_name: string;
  font_size: number;
  overrides: Record<string, string>;
  available_styles: string[];
}

// ASS colour fields are stored as &HAABBGGRR. The HTML <input type=color>
// gives #RRGGBB. We convert both ways and let alpha default to 00 (opaque).
function assToHex(ass: string | undefined): string {
  if (!ass) return "#FFFFFF";
  // &HAABBGGRR -> R=last2, G=mid, B=first
  const m = ass.match(/^&H([0-9A-Fa-f]{8})$/);
  if (!m) return "#FFFFFF";
  const v = m[1];
  const bb = v.slice(2, 4);
  const gg = v.slice(4, 6);
  const rr = v.slice(6, 8);
  return `#${rr}${gg}${bb}`.toUpperCase();
}

function hexToAss(hex: string, alpha = "00"): string {
  const m = hex.match(/^#([0-9A-Fa-f]{6})$/);
  if (!m) return "&H00FFFFFF";
  const v = m[1];
  const rr = v.slice(0, 2);
  const gg = v.slice(2, 4);
  const bb = v.slice(4, 6);
  return `&H${alpha}${bb}${gg}${rr}`.toUpperCase();
}

const ALIGNMENTS = [
  { value: "1", label: "↙" },
  { value: "2", label: "↓" },
  { value: "3", label: "↘" },
  { value: "4", label: "←" },
  { value: "5", label: "·" },
  { value: "6", label: "→" },
  { value: "7", label: "↖" },
  { value: "8", label: "↑" },
  { value: "9", label: "↗" },
];

export function StyleForm({ jobId, onChange, className }: Props) {
  const [data, setData] = useState<StyleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch initial state.
  useEffect(() => {
    let cancelled = false;
    fetch(`/api/jobs/${jobId}/style`)
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  async function patch(payload: Partial<StyleResponse> & { overrides?: Record<string, string> }) {
    try {
      const r = await fetch(`/api/jobs/${jobId}/style`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`PATCH /style -> ${r.status}`);
      const next: StyleResponse = await r.json();
      setData(next);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!data) {
    return (
      <div className={cn("p-4 text-sm text-muted", className)}>
        スタイルを読み込み中…
      </div>
    );
  }

  const ov = data.overrides;
  return (
    <div className={cn("space-y-4 p-4 text-sm overflow-auto", className)}>
      <header>
        <h2 className="text-xs uppercase tracking-wider text-muted">スタイル</h2>
      </header>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">プリセット</label>
        <select
          value={data.style_name}
          onChange={(e) => patch({ style_name: e.target.value })}
          className="w-full bg-white/5 px-2 py-1.5 rounded"
        >
          {data.available_styles.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </section>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">
          フォントサイズ: {data.font_size}px
        </label>
        <input
          type="range"
          min={10}
          max={120}
          value={data.font_size}
          onChange={(e) => patch({ font_size: Number(e.target.value) })}
          className="w-full"
        />
      </section>

      <section className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs text-muted">本文色</label>
          <input
            type="color"
            value={assToHex(ov.PrimaryColour)}
            onChange={(e) =>
              patch({ overrides: { PrimaryColour: hexToAss(e.target.value) } })
            }
            className="h-9 w-full rounded bg-transparent"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-muted">縁取り色</label>
          <input
            type="color"
            value={assToHex(ov.OutlineColour)}
            onChange={(e) =>
              patch({ overrides: { OutlineColour: hexToAss(e.target.value) } })
            }
            className="h-9 w-full rounded bg-transparent"
          />
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs text-muted">縁取り太さ</label>
          <input
            type="number"
            min={0}
            max={10}
            value={ov.Outline ?? "2"}
            onChange={(e) => patch({ overrides: { Outline: e.target.value } })}
            className="w-full bg-white/5 px-2 py-1.5 rounded"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-muted">影</label>
          <input
            type="number"
            min={0}
            max={10}
            value={ov.Shadow ?? "0"}
            onChange={(e) => patch({ overrides: { Shadow: e.target.value } })}
            className="w-full bg-white/5 px-2 py-1.5 rounded"
          />
        </div>
      </section>

      <section className="space-y-1.5">
        <label className="text-xs text-muted">配置</label>
        <div className="grid grid-cols-3 gap-1">
          {ALIGNMENTS.map((a) => (
            <button
              key={a.value}
              onClick={() => patch({ overrides: { Alignment: a.value } })}
              className={cn(
                "px-2 py-2 rounded text-base",
                (ov.Alignment ?? "2") === a.value
                  ? "bg-accent text-white"
                  : "bg-white/5 hover:bg-white/10"
              )}
            >
              {a.label}
            </button>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-3 gap-2">
        {(["MarginL", "MarginR", "MarginV"] as const).map((k) => (
          <div key={k} className="space-y-1.5">
            <label className="text-xs text-muted">{k.replace("Margin", "余白")}</label>
            <input
              type="number"
              min={0}
              max={500}
              value={ov[k] ?? ""}
              placeholder="auto"
              onChange={(e) =>
                patch({ overrides: { [k]: e.target.value } as Record<string, string> })
              }
              className="w-full bg-white/5 px-2 py-1.5 rounded"
            />
          </div>
        ))}
      </section>

      {(["Bold", "Italic", "Underline"] as const).map((k) => (
        <label
          key={k}
          className="flex items-center gap-2 text-sm select-none cursor-pointer"
        >
          <input
            type="checkbox"
            checked={ov[k] === "-1"}
            onChange={(e) =>
              patch({ overrides: { [k]: e.target.checked ? "-1" : "0" } as Record<string, string> })
            }
          />
          <span>{k}</span>
        </label>
      ))}

      {error ? <div className="text-xs text-danger">{error}</div> : null}
    </div>
  );
}
