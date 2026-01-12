import { buildQueryString, fetchWithErrorHandling } from "./utils";

// =============================================================================
// TDD Test Types
// =============================================================================

export interface TddTest {
  id: number;
  project_id: string;
  test_id: string;
  name: string;
  test_type: string;
  command: string | null;
  script: string | null;
  config: Record<string, unknown>;
  working_dir: string | null;
  timeout_seconds: number;
  last_run_at: string | null;
  last_result: string | null;
  last_duration_ms: number | null;
  last_output: string | null;
  last_error: string | null;
  run_count: number;
  pass_count: number;
  fail_count: number;
  flaky_score: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddTestRunHistory {
  id: number;
  test_id: number;
  run_type: string;
  result: string;
  duration_ms: number;
  output: string | null;
  error: string | null;
  evidence_path: string | null;
  triggered_by: string | null;
  created_at: string | null;
}

export interface TddTestWithHistory extends TddTest {
  run_history: TddTestRunHistory[];
}

export interface TestRunResult {
  test_id: string;
  result: string;
  duration_ms: number;
  output: string | null;
  error: string | null;
}

export interface ImportTestsResult {
  imported_count: number;
  skipped_count: number;
  tests: TddTest[];
  errors: string[];
}

// =============================================================================
// TDD Tests API
// =============================================================================

export async function fetchTddTests(
  projectId: string,
  type?: string,
): Promise<TddTest[]> {
  const query = buildQueryString({ type });
  return fetchWithErrorHandling(`/api/projects/${projectId}/tests${query}`, {
    errorMessage: "Failed to fetch tests",
  });
}

export async function fetchTddTest(
  projectId: string,
  testId: string,
): Promise<TddTestWithHistory> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tests/${testId}`, {
    errorMessage: "Failed to fetch test",
  });
}

export async function runTddTest(
  projectId: string,
  testId: string,
): Promise<TestRunResult> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tests/${testId}/run`,
    {
      method: "POST",
      errorMessage: "Failed to run test",
    },
  );
}

export async function runTddTests(
  projectId: string,
  options: { testIds?: string[]; tier?: string },
): Promise<TestRunResult[]> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tests/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_ids: options.testIds,
      tier: options.tier,
    }),
    errorMessage: "Failed to run tests",
  });
}

export async function importTddTests(
  projectId: string,
  sourceType: string = "all",
  discover: boolean = true,
): Promise<ImportTestsResult> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tests/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: sourceType,
      discover,
    }),
    errorMessage: "Failed to import tests",
  });
}
