// Subtitle quality heuristics. Centralised so the grid, the inspector, and the
// burn-in preview share the same thresholds.
//
// Defaults follow the audit findings:
// - Netflix English adult: 20 cps
// - Netflix children: 17 cps
// - BBC: ~15 cps (older audiences)
// - Japanese AVT: 4-7 chars/sec is typical
// We surface ja-aware thresholds because the project is Mac-first and the
// primary use case is Japanese subtitles.

export interface CpsThresholds {
  warn: number;
  danger: number;
  maxLineLength: number;
}

export const DEFAULT_CPS_THRESHOLDS: Record<string, CpsThresholds> = {
  ja: { warn: 7, danger: 9, maxLineLength: 18 },
  zh: { warn: 7, danger: 9, maxLineLength: 18 },
  ko: { warn: 8, danger: 10, maxLineLength: 18 },
  en: { warn: 17, danger: 21, maxLineLength: 42 },
  fr: { warn: 17, danger: 21, maxLineLength: 42 },
  de: { warn: 17, danger: 21, maxLineLength: 42 },
  es: { warn: 17, danger: 21, maxLineLength: 42 },
};

export function thresholdsFor(lang: string | null | undefined): CpsThresholds {
  if (!lang) return DEFAULT_CPS_THRESHOLDS.en;
  return DEFAULT_CPS_THRESHOLDS[lang] ?? DEFAULT_CPS_THRESHOLDS.en;
}

export function charsPerSecond(text: string, durationSec: number): number {
  if (durationSec <= 0) return Infinity;
  // Visual character count — strip leading/trailing whitespace.
  return text.trim().length / durationSec;
}

export type Severity = "ok" | "warn" | "danger";

export function cpsSeverity(
  cps: number,
  thresholds: CpsThresholds
): Severity {
  if (cps >= thresholds.danger) return "danger";
  if (cps >= thresholds.warn) return "warn";
  return "ok";
}

export function lineLengthSeverity(
  line: string,
  thresholds: CpsThresholds
): Severity {
  const len = line.length;
  if (len > thresholds.maxLineLength * 1.2) return "danger";
  if (len > thresholds.maxLineLength) return "warn";
  return "ok";
}

// Pick the worst severity across multiple lines.
export function worstSeverity(severities: Severity[]): Severity {
  if (severities.includes("danger")) return "danger";
  if (severities.includes("warn")) return "warn";
  return "ok";
}

export function severityClasses(
  s: Severity
): { dot: string; text: string; bg: string } {
  switch (s) {
    case "danger":
      return {
        dot: "bg-danger",
        text: "text-danger",
        bg: "bg-danger/10",
      };
    case "warn":
      return {
        dot: "bg-warn",
        text: "text-warn",
        bg: "bg-warn/10",
      };
    default:
      return {
        dot: "bg-emerald-500",
        text: "text-emerald-500",
        bg: "bg-emerald-500/5",
      };
  }
}

export function formatTimecode(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00:00.00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${h}:${m.toString().padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}
