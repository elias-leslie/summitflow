// API Base URL - always empty to use relative URLs
// Next.js rewrites proxy /api/* to backend (works for both SSR and client-side)
// Build: 2025-12-17-v6
function getApiBase(): string {
  return "";
}

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
  const res = await fetch(`${getApiBase()}/api/projects`);
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProject(id: string): Promise<Project> {
  const res = await fetch(`${getApiBase()}/api/projects/${id}`);
  if (!res.ok) throw new Error("Failed to fetch project");
  return res.json();
}

export async function fetchProjectHealth(id: string): Promise<ProjectHealth> {
  const res = await fetch(`${getApiBase()}/api/projects/${id}/health`);
  if (!res.ok) throw new Error("Failed to check project health");
  return res.json();
}

export async function createProject(project: {
  id: string;
  name: string;
  base_url: string;
  health_endpoint?: string;
}): Promise<Project> {
  const res = await fetch(`${getApiBase()}/api/projects`, {
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
  const res = await fetch(`${getApiBase()}/api/projects/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete project");
}

// ============================================================================
// Common Types (used by Explorer)
// ============================================================================

export type HealthStatus = "healthy" | "warning" | "error" | "unknown";

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
    `${getApiBase()}/api/projects/${projectId}/evidence/${featureId}/${criterionId}?${params}`
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
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/evidence/refresh`, {
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
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, notes }),
  });
  if (!res.ok) throw new Error("Failed to submit review");
  return res.json();
}

export function getScreenshotUrl(projectId: string, featureId: string, criterionId: string, version: number): string {
  return `${getApiBase()}/api/projects/${projectId}/evidence/${featureId}/${criterionId}/screenshot?version=${version}`;
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
    `${getApiBase()}/api/projects/${projectId}/features${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch features");
  return res.json();
}

export async function fetchFeatureSummary(projectId: string): Promise<FeatureSummary> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/features/summary`);
  if (!res.ok) throw new Error("Failed to fetch feature summary");
  return res.json();
}

export async function fetchVerificationSummary(projectId: string): Promise<VerificationSummary> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/features/verification-summary`);
  if (!res.ok) throw new Error("Failed to fetch verification summary");
  return res.json();
}

// ============================================================================
// Vision Types
// ============================================================================

export interface VisionGoal {
  code: string;
  name: string;
  description: string | null;
  category: string | null;
  feature_count: number;
  criteria_total: number;
  criteria_passed: number;
  pass_rate: number;
}

export interface FeatureLink {
  feature_id: string;
  name: string;
  criteria_total: number;
  criteria_passed: number;
}

export interface VisionGoalDetail extends VisionGoal {
  features: FeatureLink[];
}

export interface VisionContentItem {
  id: number;
  content_type: string;
  content_key: string;
  title: string | null;
  content: string;
  order_num: number;
  metadata: Record<string, unknown> | null;
}

export interface VisionContentResponse {
  content_types: string[];
  content: Record<string, VisionContentItem[]>;
}

export interface GoalDetail {
  id: number;
  goal_code: string;
  detail_type: string;
  content: string;
  order_num: number;
  metadata: Record<string, unknown> | null;
}

// ============================================================================
// Vision API Functions
// ============================================================================

export async function fetchVisionGoals(projectId: string): Promise<VisionGoal[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals`);
  if (!res.ok) throw new Error("Failed to fetch vision goals");
  return res.json();
}

export async function fetchVisionGoal(projectId: string, code: string): Promise<VisionGoalDetail> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals/${code}`);
  if (!res.ok) throw new Error("Failed to fetch vision goal");
  return res.json();
}

export async function fetchVisionGoalDetails(projectId: string, code: string): Promise<GoalDetail[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals/${code}/details`);
  if (!res.ok) {
    // Goal details may not exist - return empty array
    if (res.status === 404) return [];
    throw new Error("Failed to fetch vision goal details");
  }
  return res.json();
}

export async function fetchVisionContent(projectId: string): Promise<VisionContentResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision`);
  if (!res.ok) throw new Error("Failed to fetch vision content");
  return res.json();
}


// ============================================================================
// Beads Types (Issue Tracking)
// ============================================================================

export interface Bead {
  id: string;
  title: string;
  description: string | null;
  notes: string | null;
  status: "open" | "in_progress" | "closed";
  priority: number;
  issue_type: string;
  labels: string[] | null;
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
  dependency_count: number | null;
  dependent_count: number | null;
}

export interface BeadsListResponse {
  beads: Bead[];
  total: number;
  stats: {
    total: number;
    open: number;
    closed: number;
    in_progress: number;
    by_priority: Record<number, number>;
    by_type: Record<string, number>;
  };
}

export interface BeadStatsResponse {
  total: number;
  open: number;
  closed: number;
  in_progress: number;
  by_priority: Record<number, number>;
  by_type: Record<string, number>;
}

// ============================================================================
// Beads API Functions
// ============================================================================

export async function fetchBeads(
  projectId: string,
  status?: "all" | "open" | "closed",
  limit = 100
): Promise<BeadsListResponse> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/beads${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch beads");
  return res.json();
}

export async function fetchReadyBeads(projectId: string): Promise<BeadsListResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/ready`);
  if (!res.ok) throw new Error("Failed to fetch ready beads");
  return res.json();
}

export async function fetchBeadStats(projectId: string): Promise<BeadStatsResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/stats`);
  if (!res.ok) throw new Error("Failed to fetch bead stats");
  return res.json();
}

export async function fetchBead(projectId: string, beadId: string): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}`);
  if (!res.ok) throw new Error("Failed to fetch bead");
  return res.json();
}

export async function createBead(
  projectId: string,
  bead: {
    title: string;
    description?: string;
    priority?: number;
    issue_type?: string;
    labels?: string[];
  }
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bead),
  });
  if (!res.ok) throw new Error("Failed to create bead");
  return res.json();
}

export async function updateBead(
  projectId: string,
  beadId: string,
  updates: {
    status?: string;
    priority?: number;
    title?: string;
    notes?: string;
    labels?: string[];
  }
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update bead");
  return res.json();
}

export async function closeBead(
  projectId: string,
  beadId: string,
  reason: string
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error("Failed to close bead");
  return res.json();
}
