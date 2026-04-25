// Mirrors apps/api/models/segment.py and apps/api/routers/{jobs,segments}.py.
// Phase 6 will autogenerate this from FastAPI's OpenAPI; for now it is a
// hand-maintained slice that matches what the editor consumes.

export type Stage =
  | "download"
  | "convert"
  | "transcribe"
  | "translate"
  | "write"
  | "burn";

export interface JobProgress {
  stage: Stage;
  pct: number;
  msg: string;
  eta_sec?: number | null;
}

export interface JobStatus {
  id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error: string | null;
  last_stage: Stage | null;
  last_pct: number | null;
  last_msg: string | null;
  outputs: Record<string, string>;
}

export interface Word {
  start: number;
  end: number;
  text: string;
  prob: number;
}

export interface Segment {
  id: number;
  start: number;
  end: number;
  text: string;
  original_text: string | null;
  words: Word[];
  speaker: string | null;
  locked: boolean;
  avg_logprob: number | null;
  updated_at: string;
}

export interface SegmentsResponse {
  job_id: string;
  source_language: string | null;
  target_language: string | null;
  width: number;
  height: number;
  segments: Segment[];
}

export interface SegmentEdit {
  start?: number;
  end?: number;
  text?: string;
  speaker?: string | null;
  locked?: boolean;
}

export type OutputFormat = "srt" | "ass" | "fcpxml";

export interface CreateJobInput {
  source: string;
  target_lang?: string | null;
  formats: OutputFormat[];
  output_dir?: string;
  style_name?: string;
  font_size?: number;
  backend?: "auto" | "mlx" | "faster_whisper";
  model?: string;
  language?: string | null;
  vad_filter?: boolean;
}
