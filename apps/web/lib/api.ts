import type {
  CreateJobInput,
  JobStatus,
  SegmentEdit,
  SegmentsResponse,
} from "./types";

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${init?.method ?? "GET"} ${input} -> ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),

  listJobs: () => request<JobStatus[]>("/api/jobs"),

  createJob: (body: CreateJobInput) =>
    request<JobStatus>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getJob: (id: string) => request<JobStatus>(`/api/jobs/${id}`),

  cancelJob: (id: string) =>
    request<JobStatus>(`/api/jobs/${id}/cancel`, { method: "POST" }),

  getSegments: (id: string) =>
    request<SegmentsResponse>(`/api/jobs/${id}/segments`),

  patchSegments: (id: string, edits: Record<number, SegmentEdit>) =>
    request<SegmentsResponse>(`/api/jobs/${id}/segments`, {
      method: "PATCH",
      body: JSON.stringify({ edits }),
    }),

  retranslate: (id: string, segmentId: number, candidates: number) =>
    request<{ candidates: string[] }>(
      `/api/jobs/${id}/segments/${segmentId}/retranslate`,
      { method: "POST", body: JSON.stringify({ candidates }) }
    ),

  regenerateOutputs: (id: string) =>
    request<Record<string, string>>(`/api/jobs/${id}/regenerate`, {
      method: "POST",
    }),

  burn: (id: string, sourceFormat?: string) =>
    request<{ status: string }>(`/api/jobs/${id}/burn`, {
      method: "POST",
      body: JSON.stringify({ source_format: sourceFormat ?? null }),
    }),

  styles: () => request<Record<string, Record<string, string>>>("/api/styles"),
};

export function downloadUrl(jobId: string, fmt: string): string {
  return `/api/jobs/${jobId}/outputs/${fmt}`;
}

export function progressStreamUrl(jobId: string): string {
  return `/sse/jobs/${jobId}`;
}
