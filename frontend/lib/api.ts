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

// ============================================================================
// Evidence Types
// ============================================================================

export interface Evidence {
  metadata: {
    url: string;
    featureId: string;
    criterionId: string;
    version: number;
    capturedAt: string;
    pageTitle: string;
    viewport: { width: number; height: number };
    captureTimeMs: number;
  };
  console: {
    errorCount: number;
    warningCount: number;
    errors: Array<{ text: string; source: string | null }>;
    warnings: Array<{ text: string; source: string | null }>;
  };
  network: {
    totalRequests: number;
    failedRequests: number;
    failures: Array<{ url: string; status: number | string; error?: string }>;
    slowRequests: Array<{ url: string; durationMs: number }>;
  };
  pageState: {
    hasContent: boolean;
    visibleTextSample: string;
    keyElements: {
      tables: number;
      charts: number;
      buttons: number;
      errorMessages: number;
      loadingSpinners: number;
      emptyStates: number;
    };
  };
  performance: {
    pageLoadMs: number | null;
    domContentLoadedMs: number | null;
    largestContentfulPaintMs: number | null;
  };
}

export interface Artifact {
  id: number;
  artifactId: string;
  featureId: string;
  criterionId: string;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  expiresAt: string;
  qualityStatus: string;
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number;
}

export interface ArtifactResponse {
  artifact: Artifact;
  versions: Artifact[];
  evidence: Evidence | null;
  screenshotUrl: string;
  evidenceUrl: string;
}

// ============================================================================
// Evidence API Functions
// ============================================================================

export async function fetchEvidence(
  projectId: string,
  featureId: string,
  criterionId: string,
  version?: number,
  includeEvidence = true
): Promise<ArtifactResponse> {
  const params = new URLSearchParams();
  params.append("include_evidence", includeEvidence.toString());
  if (version) params.append("version", version.toString());

  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/evidence/${featureId}/${criterionId}?${params}`
  );
  if (!res.ok) {
    if (res.status === 404) throw new Error("No evidence captured yet");
    throw new Error("Failed to fetch evidence");
  }
  return res.json();
}

export async function refreshEvidence(
  projectId: string,
  featureId: string,
  criterionId: string,
  url: string
): Promise<{ success: boolean; version?: number; error?: string }> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/evidence/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feature_id: featureId, criterion_id: criterionId, url }),
  });
  if (!res.ok) throw new Error("Failed to refresh evidence");
  return res.json();
}

export async function submitEvidenceReview(
  projectId: string,
  evidenceId: string,
  approved: boolean | null,
  notes?: string
): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/evidence/${evidenceId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, notes }),
  });
  if (!res.ok) throw new Error("Failed to submit review");
  return res.json();
}

export function getScreenshotUrl(projectId: string, featureId: string, criterionId: string, version: number): string {
  return `${API_BASE}/api/projects/${projectId}/evidence/${featureId}/${criterionId}/screenshot?version=${version}`;
}

// ============================================================================
// Feature Types
// ============================================================================

export interface AcceptanceCriterion {
  id: string;
  criterion: string;
  verification: string;
  type: string;
  passed: boolean | null;
  verified_at: string | null;
  verification_output: string | null;
}

export interface Feature {
  id: number | null;
  project_id: string;
  feature_id: string;
  name: string;
  category: string | null;
  description: string | null;
  layers: string[];
  layer_results: Record<string, { passed: boolean; evidence?: string }>;
  total_tasks: number;
  completed_tasks: number;
  completion_pct: number;
  health_status: string;
  last_verified_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  priority: number | null;
  effective_priority: number;
  acceptance_criteria: AcceptanceCriterion[];
  vision_goals: string[];
}

export interface FeaturesListResponse {
  features: Feature[];
  total: number;
  filtered: number;
}

export interface FeatureSummary {
  total: number;
  category_breakdown: Record<string, number>;
  health_breakdown: Record<string, number>;
}

export interface VerificationSummary {
  total_criteria: number;
  passed: number;
  failed: number;
  pending: number;
  by_type: Record<string, { total: number; passed: number; failed: number; pending: number }>;
  last_run_at: string | null;
}

// ============================================================================
// Feature API Functions
// ============================================================================

export async function fetchFeatures(
  projectId: string,
  options: {
    category?: string;
    health_status?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<FeaturesListResponse> {
  const params = new URLSearchParams();
  if (options.category) params.append("category", options.category);
  if (options.health_status) params.append("health_status", options.health_status);
  if (options.limit) params.append("limit", options.limit.toString());
  if (options.offset) params.append("offset", options.offset.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/features${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch features");
  return res.json();
}

export async function fetchFeatureSummary(projectId: string): Promise<FeatureSummary> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/features/summary`);
  if (!res.ok) throw new Error("Failed to fetch feature summary");
  return res.json();
}

export async function fetchVerificationSummary(projectId: string): Promise<VerificationSummary> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/features/verification-summary`);
  if (!res.ok) throw new Error("Failed to fetch verification summary");
  return res.json();
}
