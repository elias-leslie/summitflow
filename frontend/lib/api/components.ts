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
  criteria: CriterionWithTests[];
}

// Criterion linked to a capability with its tests
export interface CriterionWithTests {
  id: number;
  project_id: string;
  criterion_id: string;
  criterion: string;
  category: string;
  measurement: string;
  threshold: string | null;
  created_at: string | null;
  created_by_task_id: string | null;
  tests: {
    id: number;
    test_id: string;
    name: string;
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

// =============================================================================
// Capability Criteria API
// =============================================================================

export interface CreateCriterionRequest {
  criterion: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: "test" | "metric" | "tool" | "manual";
  threshold?: string;
}

export interface CriterionResponse {
  id: number;
  criterion_id: string;
  criterion: string;
  category: string;
  measurement: string;
  threshold: string | null;
  created_at: string | null;
  tests: unknown[];
}

export async function createCapabilityCriterion(
  projectId: string,
  capabilityId: string,
  request: CreateCriterionRequest
): Promise<CriterionResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/capabilities/${capabilityId}/criteria`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      errorMessage: "Failed to create criterion",
    }
  );
}

export async function deleteCapabilityCriterion(
  projectId: string,
  capabilityId: string,
  criterionId: string
): Promise<{ status: string; criterion_id: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/capabilities/${capabilityId}/criteria/${criterionId}`,
    { method: "DELETE", errorMessage: "Failed to delete criterion" }
  );
}

export async function linkTestToCriterion(
  projectId: string,
  capabilityId: string,
  criterionId: string,
  testId: number,
  isPrimary: boolean = false
): Promise<{ status: string; criterion_id: string; test_id: number }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/capabilities/${capabilityId}/criteria/${criterionId}/link-test`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test_id: testId, is_primary: isPrimary }),
      errorMessage: "Failed to link test to criterion",
    }
  );
}

export interface UpdateCriterionRequest {
  criterion?: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: "test" | "metric" | "tool" | "manual";
  threshold?: string;
}

export async function updateCriterion(
  projectId: string,
  criterionId: string,
  request: UpdateCriterionRequest
): Promise<CriterionResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/criteria/${criterionId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      errorMessage: "Failed to update criterion",
    }
  );
}

export async function unlinkTestFromCriterion(
  projectId: string,
  criterionId: string,
  testId: number
): Promise<{ status: string; criterion_id: string; test_id: number }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/criteria/${criterionId}/test/${testId}`,
    { method: "DELETE", errorMessage: "Failed to unlink test from criterion" }
  );
}

// =============================================================================
// Batch Creation API
// =============================================================================

export interface BatchComponentCreateItem {
  component_id: string;
  name: string;
  description?: string;
  priority?: number;
  explorer_entry_id?: number;
}

export interface BatchCreateResult {
  component_id: string;
  success: boolean;
  id?: number;
  error?: string;
}

export interface BatchComponentResponse {
  created: TddComponent[];
  errors: BatchCreateResult[];
}

export async function batchCreateComponents(
  projectId: string,
  items: BatchComponentCreateItem[]
): Promise<BatchComponentResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/components/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
    errorMessage: "Failed to batch create components",
  });
}

// Capability batch creation
export interface BatchCriterionCreate {
  criterion: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: "test" | "metric" | "tool" | "manual";
  threshold?: string;
}

export interface BatchCapabilityCreateItem {
  component_id: number;
  capability_id: string;
  name: string;
  description?: string;
  priority?: number;
  criteria?: BatchCriterionCreate[];
}

export interface BatchCapabilityResult {
  capability_id: string;
  success: boolean;
  id?: number;
  criteria_created?: number;
  error?: string;
}

export interface BatchCapabilityResponse {
  created: TddCapability[];
  errors: BatchCapabilityResult[];
}

export async function batchCreateCapabilities(
  projectId: string,
  items: BatchCapabilityCreateItem[]
): Promise<BatchCapabilityResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/capabilities/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
    errorMessage: "Failed to batch create capabilities",
  });
}
