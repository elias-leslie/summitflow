import { buildQueryString, fetchWithErrorHandling } from "./utils";
import { fetchWithGenerationTimeout, roundtableSessionAction, buildRoundtableGenerationUrl } from "./wrappers";

// =============================================================================
// TDD Component Types
// =============================================================================

export interface TddComponent {
  id: number;
  project_id: string;
  component_id: string;
  name: string;
  description: string | null;
  priority: number;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddCapability {
  id: number;
  project_id: string;
  component_id: number;
  capability_id: string;
  name: string;
  description: string | null;
  priority: number;
  status: string;
  locked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddCapabilityWithTests extends TddCapability {
  tests: {
    id: number;
    test_id: string;
    name: string;
    test_type: string;
    last_result: string | null;
    is_primary: boolean;
  }[];
}

export interface ComponentSuggestion {
  suggested_name: string;
  type: "page_group" | "endpoint_group" | "directory";
  path: string;
  entry_count: number;
  entries: { id: number; path: string }[];
}

export interface CreateComponentRequest {
  component_id: string;
  name: string;
  description?: string;
  priority?: number;
  explorer_entry_id?: number;
}

// =============================================================================
// TDD Spec Types
// =============================================================================

export interface SpecTest {
  type: string;
  name: string;
  command?: string;
}

export interface SpecCapability {
  id: string;
  name: string;
  description?: string;
  tests: SpecTest[];
}

export interface SpecComponent {
  id: string;
  name: string;
  description?: string;
  priority?: number;
  capabilities: SpecCapability[];
}

export interface GeneratedSpec {
  components: SpecComponent[];
}

export interface GenerateSpecResponse {
  session_id: string;
  spec: GeneratedSpec;
  components_count: number;
  capabilities_count: number;
  tests_count: number;
}

export interface AcceptSpecResponse {
  spec_id: number;
  components_created: number;
  capabilities_created: number;
  tests_created: number;
}

// =============================================================================
// TDD Components API
// =============================================================================

export async function fetchTddComponents(projectId: string): Promise<TddComponent[]> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/components`, {
    errorMessage: "Failed to fetch components",
  });
}

export async function fetchComponentSuggestions(
  projectId: string,
  source: string
): Promise<ComponentSuggestion[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tdd/component-suggestions?source=${source}`,
    { errorMessage: "Failed to fetch component suggestions" }
  );
}

export async function createTddComponent(
  projectId: string,
  component: CreateComponentRequest
): Promise<TddComponent> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/components`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(component),
    errorMessage: "Failed to create component",
  });
}

export async function fetchTddComponent(
  projectId: string,
  componentId: string
): Promise<TddComponent> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/components/${componentId}`, {
    errorMessage: "Failed to fetch component",
  });
}

export async function fetchTddCapabilities(
  projectId: string,
  componentDbId?: number
): Promise<TddCapability[]> {
  const query = buildQueryString({ component: componentDbId });
  return fetchWithErrorHandling(`/api/projects/${projectId}/capabilities${query}`, {
    errorMessage: "Failed to fetch capabilities",
  });
}

export async function fetchTddCapability(
  projectId: string,
  capabilityId: string
): Promise<TddCapabilityWithTests> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/capabilities/${capabilityId}`, {
    errorMessage: "Failed to fetch capability",
  });
}

export async function lockTddCapability(
  projectId: string,
  capabilityId: string
): Promise<TddCapability> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/capabilities/${capabilityId}/lock`,
    { method: "POST", errorMessage: "Failed to lock capability" }
  );
}

// =============================================================================
// TDD Spec Generation API
// =============================================================================

export async function generateSpecFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "gemini"
): Promise<GenerateSpecResponse> {
  return fetchWithGenerationTimeout(
    buildRoundtableGenerationUrl(projectId, sessionId, "generate-spec"),
    { agent_type: agent },
    "Failed to generate spec"
  );
}

export async function getSpecFromRoundtable(
  projectId: string,
  sessionId: string
): Promise<{ session_id: string; spec: GeneratedSpec | null }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/sessions/${sessionId}/spec`,
    { errorMessage: "Failed to get spec" }
  );
}

export async function acceptSpecFromRoundtable(
  projectId: string,
  sessionId: string,
  acceptedBy: string = "user"
): Promise<AcceptSpecResponse> {
  return roundtableSessionAction(
    projectId, sessionId, "accept-spec",
    { accepted_by: acceptedBy },
    "Failed to accept spec"
  );
}
