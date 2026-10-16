import type { CaptionLine, Job, JobOptions, JobSummary, PublicConfig, RenderOptions } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError("Can't reach the ClipForge server. Is the backend running?", 0);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    let message = `Request failed (${res.status})`;
    let code: string | undefined;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object" && "message" in detail) {
      message = String((detail as { message: string }).message);
      code = (detail as { code?: string }).code;
    } else if (Array.isArray(detail) && detail[0]?.msg) {
      message = detail.map((d: { loc?: string[]; msg: string }) => `${(d.loc || []).slice(-1)[0] ?? ""}: ${d.msg}`).join("; ");
    }
    throw new ApiError(message, res.status, code);
  }
  return body as T;
}

export const api = {
  config: () => request<PublicConfig>("/api/config"),
  validate: (url: string) =>
    request<{ valid: boolean; error?: string; code?: string; video_id?: string; kind?: string }>(
      `/api/validate?url=${encodeURIComponent(url)}`,
    ),
  createJob: (url: string, authorized: boolean, options: JobOptions) =>
    request<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ url, authorized, options }) }),
  createDemo: (options: JobOptions) => request<Job>("/api/demo", { method: "POST", body: JSON.stringify(options) }),
  listJobs: () => request<JobSummary[]>("/api/jobs"),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  deleteJob: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  updateClip: (
    jobId: string,
    clipId: string,
    patch: { start?: number; end?: number; captions?: CaptionLine[]; render?: RenderOptions },
  ) => request<Job>(`/api/jobs/${jobId}/clips/${clipId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  regenerateClip: (jobId: string, clipId: string) =>
    request<Job>(`/api/jobs/${jobId}/clips/${clipId}/regenerate`, { method: "POST" }),
  deleteClip: (jobId: string, clipId: string) =>
    request<Job>(`/api/jobs/${jobId}/clips/${clipId}`, { method: "DELETE" }),
  cleanup: (hours: number) =>
    request<{ removed: string[]; disk_usage_bytes: number }>(`/api/cleanup?older_than_hours=${hours}`, { method: "POST" }),
};

export const urls = {
  clipVideo: (jobId: string, clip: { id: string; version: number }, download = false) =>
    `${BASE}/api/jobs/${jobId}/clips/${clip.id}/video?v=${clip.version}${download ? "&download=true" : ""}`,
  clipThumb: (jobId: string, clip: { id: string; version: number }) =>
    `${BASE}/api/jobs/${jobId}/clips/${clip.id}/thumbnail?v=${clip.version}`,
  sourceThumb: (jobId: string) => `${BASE}/api/jobs/${jobId}/thumbnail`,
  zip: (jobId: string) => `${BASE}/api/jobs/${jobId}/download.zip`,
};
