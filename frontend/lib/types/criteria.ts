/**
 * Acceptance criteria types for TDD architecture.
 */

/**
 * Base acceptance criterion - reusable across capabilities and tasks.
 */
export interface AcceptanceCriterion {
  id: number;
  criterion_id: string; // Format: ac-NNN
  criterion: string;
  category: "performance" | "correctness" | "security" | "quality";
  measurement: "test" | "metric" | "tool" | "manual";
  threshold?: string;
}

/**
 * Task-specific criterion with verification state.
 */
export interface TaskCriterion extends AcceptanceCriterion {
  verified: boolean;
  verified_at?: string;
  verified_by?: "opus" | "test" | "human" | "agent";
}

/**
 * Criterion with linked tests (for capability context).
 */
export interface CriterionWithTests extends AcceptanceCriterion {
  created_at?: string;
  created_by_task_id?: string;
  tests: CriterionTest[];
}

/**
 * Test linked to a criterion.
 */
export interface CriterionTest {
  id: number;
  test_id: string;
  name: string;
  last_result?: string;
  is_primary: boolean;
}

/**
 * Request to create a new criterion.
 */
export interface CreateCriterionRequest {
  criterion: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: "test" | "metric" | "tool" | "manual";
  threshold?: string;
}

/**
 * Request to link a test to a criterion.
 */
export interface LinkTestRequest {
  test_id: number;
  is_primary?: boolean;
}
