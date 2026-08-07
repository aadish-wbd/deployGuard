import type {
  DashboardStats,
  HealthResponse,
  IncidentListResponse,
  IncidentRecord,
  WorkflowStatus,
} from "./types";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export async function fetchDashboardStats(service?: string): Promise<DashboardStats | null> {
  try {
    const query = service ? `?service=${encodeURIComponent(service)}` : "";
    return await request<DashboardStats>(`/api/v1/dashboard/stats${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) return null;
    throw error;
  }
}

export async function fetchIncidents(params: {
  service?: string;
  status?: string;
  limit?: number;
  page_token?: string;
}): Promise<IncidentListResponse> {
  const search = new URLSearchParams();
  if (params.service) search.set("service", params.service);
  if (params.status) search.set("status", params.status);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.page_token) search.set("page_token", params.page_token);
  const qs = search.toString();
  return request<IncidentListResponse>(`/api/v1/incidents${qs ? `?${qs}` : ""}`);
}

export async function fetchIncident(id: string): Promise<IncidentRecord> {
  return request<IncidentRecord>(`/api/v1/incidents/${id}`);
}

export async function updateIncidentWorkflowStatus(
  id: string,
  workflowStatus: WorkflowStatus,
): Promise<IncidentRecord> {
  return request<IncidentRecord>(`/api/v1/incidents/${id}/workflow-status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow_status: workflowStatus }),
  });
}

export async function downloadRcaReport(id: string): Promise<void> {
  const response = await fetch(`/api/v1/incidents/${id}/rca`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `rca-${id}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export { ApiError };
