import type {
  CaseDetail,
  CaseSummary,
  Clip,
  Preflight,
  RegistrySnapshot,
  Entity,
  Health,
  MatchResult,
  MatchTestPayload,
  OverridePayload,
  PlateFormat,
  ReviewStatus,
  AuditEntry,
  RegistryVehicle,
  VehicleDetail,
  VehicleSummary,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new Error("Backend is unreachable. Check that the API server is running on port 8000.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail?.message ?? `Request failed (${response.status})`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface ClipUpload {
  file: File;
  camera_label: string;
  location: string;
  recorded_at: string;
  timezone: string;
  latitude: string;
  longitude: string;
  plate_format: PlateFormat;
}

export const api = {
  health: () => request<Health>("/health"),
  listCases: () => request<CaseSummary[]>("/cases"),
  getCase: (id: string) => request<CaseDetail>(`/cases/${id}`),
  createCase: (title: string) => request<CaseDetail>("/cases", json({ title })),
  uploadClips: (id: string, uploads: ClipUpload[]) => {
    const form = new FormData();
    for (const item of uploads) {
      form.append("files", item.file);
      form.append("camera_label", item.camera_label);
      form.append("location", item.location);
      form.append("recorded_at", item.recorded_at);
      form.append("timezone", item.recorded_at ? item.timezone : "");
      form.append("latitude", item.latitude);
      form.append("longitude", item.longitude);
      form.append("plate_format", item.plate_format);
    }
    return request<{ clips: Clip[] }>(`/cases/${id}/clips`, { method: "POST", body: form });
  },
  updateClip: (id: string, clipId: string, body: { recorded_at?: string | null; timezone?: string | null; plate_format?: PlateFormat }) =>
    request<Clip>(`/cases/${id}/clips/${clipId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  reviewLink: (id: string, entityId: string, decision: ReviewStatus, note?: string) =>
    request<Entity>(`/cases/${id}/entities/${entityId}/review`, json({ decision, note })),
  analyze: (id: string, acknowledgeNoCoverage = false) =>
    request<{ status: string }>(`/cases/${id}/analyze`, json({ acknowledge_no_coverage: acknowledgeNoCoverage })),
  preflight: (id: string) => request<Preflight>(`/cases/${id}/preflight`),
  cancel: (id: string) => request<{ status: string }>(`/cases/${id}/cancel`, { method: "POST" }),
  rescore: (id: string) =>
    request<{ before: Record<string, number>; after: Record<string, number>; tracks: number }>(`/cases/${id}/rescore`, { method: "POST" }),
  registryCoverage: () =>
    request<RegistrySnapshot & { formats: { plate_format: PlateFormat; label: string; compatible_records: number }[] }>("/registry/coverage"),
  vehicles: (id: string) => request<{ vehicles: VehicleSummary[]; entities: Entity[] }>(`/cases/${id}/vehicles`),
  vehicle: (id: string, vehicleId: string) => request<VehicleDetail>(`/cases/${id}/vehicles/${vehicleId}`),
  override: (id: string, vehicleId: string, body: OverridePayload) =>
    request<{ vehicle: VehicleDetail; rerank_ms: number; audit: AuditEntry[] }>(
      `/cases/${id}/vehicles/${vehicleId}/override`,
      json(body),
    ),
  registry: (params: Record<string, string | number>) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== "" && query.set(key, String(value)));
    return request<{ items: RegistryVehicle[]; total: number; page: number; page_size: number; registry_total: number; synthetic_count: number }>(`/registry?${query}`);
  },
  uploadRegistry: (file: File, mode: "merge" | "replace") => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    return request<{ inserted: number; updated: number; rejected: number; total: number; errors: string[] }>(
      "/registry/upload",
      { method: "POST", body: form },
    );
  },
  matchTest: (body: MatchTestPayload) => request<MatchResult>("/registry/match-test", json(body)),
};

export const artifactUrl = (path?: string | null) => (path ? `/artifacts/${path}` : undefined);
export const reportHtmlUrl = (id: string, clipId?: string) => `/api/cases/${id}/report/html${clipId ? `?clip_id=${clipId}` : ""}`;
export const reportPdfUrl = (id: string, appendix = false, clipId?: string) => {
  const query = new URLSearchParams();
  if (appendix) query.set("appendix", "true");
  if (clipId) query.set("clip_id", clipId);
  const suffix = query.toString();
  return `/api/cases/${id}/report/pdf${suffix ? `?${suffix}` : ""}`;
};
export const exportUrl = (id: string, format: "csv" | "json", clipId?: string) =>
  `/api/cases/${id}/export.${format}${clipId ? `?clip_id=${clipId}` : ""}`;
export const progressUrl = (id: string) => `/api/cases/${id}/progress`;
