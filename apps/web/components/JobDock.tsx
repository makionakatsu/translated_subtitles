"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, progressStreamUrl } from "@/lib/api";
import type { JobProgress, JobStatus, Stage } from "@/lib/types";
import { cn } from "@/lib/cn";

const STAGES: Stage[] = ["download", "convert", "transcribe", "translate", "write", "burn"];

const STAGE_LABEL: Record<Stage, string> = {
  download: "DL",
  convert: "WAV",
  transcribe: "ASR",
  translate: "翻訳",
  write: "出力",
  burn: "焼込",
};

interface Props {
  className?: string;
}

export function JobDock({ className }: Props) {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  // Per-job latest progress, keyed by job id.
  const [progress, setProgress] = useState<Record<string, JobProgress>>({});

  // Poll the job list every 4s. The SSE stream below carries finer-grained
  // progress; the poll is a safety net so we recover from disconnects.
  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const list = await api.listJobs();
        if (!cancelled) setJobs(list);
      } catch {
        /* ignore — we'll retry */
      }
    }
    refresh();
    const interval = setInterval(refresh, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Subscribe to SSE for every running job. EventSource auto-reconnects.
  useEffect(() => {
    const sources: EventSource[] = [];
    for (const job of jobs) {
      if (job.status !== "running" && job.status !== "pending") continue;
      const es = new EventSource(progressStreamUrl(job.id));
      es.addEventListener("progress", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as JobProgress;
          setProgress((prev) => ({ ...prev, [job.id]: data }));
        } catch {
          /* ignore malformed event */
        }
      });
      es.addEventListener("end", () => es.close());
      sources.push(es);
    }
    return () => {
      for (const es of sources) es.close();
    };
  }, [jobs]);

  if (jobs.length === 0) return null;

  return (
    <aside
      className={cn(
        "fixed bottom-3 right-3 w-[320px] max-h-[60vh] overflow-auto rounded-xl border border-white/10 bg-bg/90 backdrop-blur-md shadow-lg p-3 space-y-2",
        className
      )}
    >
      <header className="flex items-center justify-between text-xs text-muted">
        <span>ジョブ ({jobs.length})</span>
      </header>
      {jobs.map((job) => {
        const p = progress[job.id];
        const stage = (p?.stage ?? job.last_stage) as Stage | null;
        return (
          <article
            key={job.id}
            className="rounded-lg bg-white/5 p-2 space-y-1.5"
          >
            <div className="flex items-center justify-between text-xs">
              <Link
                href={job.status === "completed" ? `/jobs/${job.id}` : "#"}
                className={cn(
                  "font-mono truncate",
                  job.status === "completed" && "text-accent hover:underline"
                )}
              >
                {job.id}
              </Link>
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded",
                  job.status === "running" && "bg-accent/20 text-accent",
                  job.status === "completed" && "bg-emerald-500/20 text-emerald-400",
                  job.status === "failed" && "bg-danger/20 text-danger",
                  job.status === "cancelled" && "bg-muted/20 text-muted"
                )}
              >
                {job.status}
              </span>
            </div>
            <div className="grid grid-cols-6 gap-0.5 text-[9px] uppercase">
              {STAGES.map((s) => {
                const active = s === stage;
                const past = STAGES.indexOf(s) < STAGES.indexOf(stage ?? "download");
                return (
                  <div
                    key={s}
                    className={cn(
                      "rounded px-1 py-0.5 text-center",
                      active && "bg-accent text-white",
                      !active && past && "bg-emerald-500/30 text-emerald-300",
                      !active && !past && "bg-white/5 text-muted"
                    )}
                    title={s}
                  >
                    {STAGE_LABEL[s]}
                  </div>
                );
              })}
            </div>
            <div className="text-[11px] text-muted truncate">
              {p?.msg ?? job.last_msg ?? "—"}
            </div>
            <div className="h-1 w-full rounded bg-white/5">
              <div
                className="h-1 rounded bg-accent transition-[width] duration-300"
                style={{ width: `${(p?.pct ?? job.last_pct ?? 0).toFixed(0)}%` }}
              />
            </div>
          </article>
        );
      })}
    </aside>
  );
}
