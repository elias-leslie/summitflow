/**
 * Evidence types for TDD architecture.
 */

/**
 * Evidence record - UI verification evidence.
 */
export type EvidenceType =
  | "screenshot"
  | "mockup"
  | "test-output"
  | "api-response"
  | "console_error";

export type MockupStatus =
  | "generated"
  | "pending_approval"
  | "approved"
  | "rejected";

export interface Evidence {
  id: number;
  evidenceId: string;
  capabilityId: string;
  criterionId: string;
  taskId: string | null;
  explorerEntryId: number | null;
  evidenceType: EvidenceType;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  qualityStatus: "pending" | "passed" | "failed" | "needs_review" | "migrated";
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number | null;
  screenshotUrl: string;
  criterionDbId: number | null;
  testRunId: number | null;
  autoCaptured: boolean;
  criterionText: string | null;
  linkedEvidenceId: number | null;
  mockupStatus: MockupStatus | null;
  environment: string | null;
  viewportName: string | null;
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
  mockup_count: number;
}

/**
 * Mockup list response from API.
 */
export interface MockupListResponse {
  mockups: Evidence[];
  total: number;
}

/**
 * Mockup comparison response - approved mockup with linked actual screenshot.
 */
export interface MockupComparisonResponse {
  mockup: Evidence;
  actualScreenshot: Evidence | null;
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
