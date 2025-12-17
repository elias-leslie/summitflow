const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export interface Project {
  id: string;
  name: string;
  base_url: string;
  health_endpoint: string;
  created_at: string;
  health_status?: string;
}

export interface ProjectHealth {
  project_id: string;
  healthy: boolean;
  status_code?: number;
  response_time_ms?: number;
  error?: string;
  checked_at: string;
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${API_BASE}/api/projects`);
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProject(id: string): Promise<Project> {
  const res = await fetch(`${API_BASE}/api/projects/${id}`);
  if (!res.ok) throw new Error("Failed to fetch project");
  return res.json();
}

export async function fetchProjectHealth(id: string): Promise<ProjectHealth> {
  const res = await fetch(`${API_BASE}/api/projects/${id}/health`);
  if (!res.ok) throw new Error("Failed to check project health");
  return res.json();
}

export async function createProject(project: {
  id: string;
  name: string;
  base_url: string;
  health_endpoint?: string;
}): Promise<Project> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to create project");
  }
  return res.json();
}

export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/projects/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete project");
}

// ============================================================================
// Sitemap Types
// ============================================================================

export type HealthStatus = "healthy" | "warning" | "error" | "unknown";

export interface SitemapEntry {
  id: number;
  port: number;
  path: string;
  method: string;
  entry_type: string;
  source: string | null;
  title: string | null;
  parent_path: string | null;
  health_status: HealthStatus;
  console_errors: number;
  console_warnings: number;
  http_status: number | null;
  response_time_ms: number | null;
  last_error_message: string | null;
  last_checked_at: string | null;
  discovered_at: string | null;
}

export interface SitemapListResponse {
  total: number;
  entries: SitemapEntry[];
}

export interface HealthSummaryResponse {
  total: number;
  healthy: number;
  warning: number;
  error: number;
  unknown: number;
  by_port: Record<string, { healthy: number; warning: number; error: number; unknown: number }>;
}

export interface DiscoveryResponse {
  backend_discovered: number;
  frontend_discovered: number;
  total_saved: number;
}

export interface HealthCheckResponse {
  success: boolean;
  entry_id?: number;
  health_status?: HealthStatus;
  http_status?: number;
  response_time_ms?: number;
  error?: string;
}

export interface CheckAllResponse {
  checked: number;
  healthy: number;
  warning: number;
  error: number;
}

// ============================================================================
// Sitemap API Functions
// ============================================================================

export async function fetchSitemapEntries(
  projectId: string,
  filters: { port?: number; health_status?: HealthStatus; limit?: number } = {}
): Promise<SitemapListResponse> {
  const params = new URLSearchParams();
  if (filters.port) params.append("port", filters.port.toString());
  if (filters.health_status) params.append("health_status", filters.health_status);
  if (filters.limit) params.append("limit", filters.limit.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/sitemap/entries${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch sitemap entries");
  return res.json();
}

export async function fetchHealthSummary(projectId: string): Promise<HealthSummaryResponse> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/sitemap/health-summary`);
  if (!res.ok) throw new Error("Failed to fetch health summary");
  return res.json();
}

export async function triggerDiscovery(projectId: string): Promise<DiscoveryResponse> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/sitemap/discover`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to trigger discovery");
  return res.json();
}

export async function checkEntryHealth(projectId: string, entryId: number): Promise<HealthCheckResponse> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/sitemap/check/${entryId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to check health");
  return res.json();
}

export async function checkAllHealth(projectId: string): Promise<CheckAllResponse> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/sitemap/check-all`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to check all health");
  return res.json();
}
