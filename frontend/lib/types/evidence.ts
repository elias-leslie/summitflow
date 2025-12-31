/**
 * Evidence types for TDD architecture.
 */

/**
 * Evidence record - UI verification evidence.
 */
export interface Evidence {
  id: number;
  evidenceId: string;
  capabilityId: string;
  criterionId: string;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  qualityStatus: "pending" | "passed" | "failed" | "needs_review" | "migrated";
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number | null;
  screenshotUrl: string;
  // New fields for criteria linkage
  criterionDbId: number | null; // FK to acceptance_criteria.id
  testRunId: number | null; // FK to test_runs.id
  autoCaptured: boolean; // True if auto-captured on test pass
  criterionText: string | null; // Human-readable criterion text from JOIN
}

/**
 * Evidence summary statistics.
 */
export interface EvidenceSummary {
  total_current: number;
  by_status: Record<string, number>;
  auto_captured_count: number;
  with_user_notes: number;
  total_storage_bytes: number;
}

/**
 * Evidence list response from API.
 */
export interface EvidenceListResponse {
  evidence: Evidence[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Request to capture new evidence.
 */
export interface CaptureEvidenceRequest {
  capability_id: string;
  criterion_id: string;
  url: string;
}

/**
 * Request to submit user review.
 */
export interface EvidenceReviewRequest {
  approved: boolean | null;
  notes?: string;
}

/**
 * Capture result from API.
 */
export interface CaptureResult {
  success: boolean;
  version?: number;
  message?: string;
  warning?: string;
  error?: string;
}
