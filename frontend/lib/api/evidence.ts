/**
 * Evidence API - capture, review, and artifact management
 *
 * Evidence is linked to task_id and/or explorer_entry_id.
 * Uses /evidence/{evidence_id} pattern for direct access.
 */

import { fetchWithErrorHandling, getApiBase } from './utils'

// ============================================================================
// Evidence Types
// ============================================================================

/** Valid evidence types */
export type EvidenceType =
  | 'screenshot'
  | 'mockup'
  | 'test-output'
  | 'api-response'
  | 'console_error'

/** Valid mockup status values */
export type MockupStatus =
  | 'generated'
  | 'pending_approval'
  | 'approved'
  | 'rejected'

/** Evidence.json file structure */
export interface EvidenceData {
  metadata: {
    url: string
    capturedAt: string
    pageTitle?: string
    viewport: { width: number; height: number }
    captureTimeMs: number
    error?: string // Present if capture failed
  }
  console: {
    errorCount: number
    warningCount: number
    errors: Array<{ text: string; source: string | null }>
    warnings: Array<{ text: string; source: string | null }>
  }
  network: {
    totalRequests: number
    failedRequests: number
    failures: Array<{ url: string; status: number | string; error?: string }>
    slowRequests: Array<{ url: string; durationMs: number }>
  }
  pageState: {
    hasContent: boolean
    visibleTextSample: string
    keyElements: {
      tables: number
      charts: number
      buttons: number
      errorMessages: number
      loadingSpinners: number
      emptyStates: number
    }
  }
  performance: {
    pageLoadMs: number | null
    domContentLoadedMs: number | null
    largestContentfulPaintMs: number | null
  }
}

/** Evidence record from database */
export interface EvidenceRecord {
  id: number
  evidenceId: string
  taskId: string | null
  explorerEntryId: number | null
  evidenceType: EvidenceType
  version: number
  isCurrent: boolean
  capturedAt: string
  qualityStatus: string
  confidence: number | null
  userApproved: boolean | null
  userNotes: string | null
  fileSizeBytes: number | null
  criterionDbId: number | null
  testRunId: number | null
  autoCaptured: boolean
  criterionText: string | null
  linkedEvidenceId: number | null
  mockupStatus: MockupStatus | null
  environment: string | null
  viewportName: string | null
  screenshotUrl?: string
}

/** Response for single evidence fetch */
export interface EvidenceResponse {
  evidence: EvidenceRecord
  screenshotUrl: string
  dataUrl: string
  data?: EvidenceData
}

/** Response for evidence list */
export interface EvidenceListResponse {
  evidence: EvidenceRecord[]
  total: number
  limit?: number
  offset?: number
}

/** Evidence capture request */
export interface CaptureRequest {
  url: string
  taskId?: string
  explorerEntryId?: number
  evidenceType?: EvidenceType
  criterionDbId?: number
  environment?: string
  viewportName?: string
}

/** Evidence capture response */
export interface CaptureResponse {
  success: boolean
  evidenceId?: string
  dbId?: number
  filePath?: string
  version?: number
  error?: string
}

// ============================================================================
// Evidence API Functions
// ============================================================================

/**
 * Get evidence by evidence_id
 */
export async function fetchEvidence(
  projectId: string,
  evidenceId: string,
  includeData = false,
): Promise<EvidenceResponse> {
  const params = new URLSearchParams()
  if (includeData) params.append('include_data', 'true')

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}?${params}`,
  )
  if (!res.ok) {
    if (res.status === 404) throw new Error('Evidence not found')
    throw new Error('Failed to fetch evidence')
  }
  return res.json()
}

/**
 * Get evidence data (evidence.json contents)
 */
export async function fetchEvidenceData(
  projectId: string,
  evidenceId: string,
): Promise<EvidenceData> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}/data`,
  )
  if (!res.ok) {
    if (res.status === 404) throw new Error('Evidence data not found')
    throw new Error('Failed to fetch evidence data')
  }
  return res.json()
}

/**
 * List evidence with optional filtering
 */
export async function listEvidence(
  projectId: string,
  options?: {
    limit?: number
    offset?: number
    taskId?: string
    entryId?: number
    evidenceType?: EvidenceType
    status?: string
    search?: string
  },
): Promise<EvidenceListResponse> {
  const params = new URLSearchParams()
  if (options?.limit) params.append('limit', options.limit.toString())
  if (options?.offset) params.append('offset', options.offset.toString())
  if (options?.taskId) params.append('task_id', options.taskId)
  if (options?.entryId) params.append('entry_id', options.entryId.toString())
  if (options?.evidenceType)
    params.append('evidence_type', options.evidenceType)
  if (options?.status) params.append('status', options.status)
  if (options?.search) params.append('search', options.search)

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence?${params}`,
  )
  if (!res.ok) {
    throw new Error('Failed to list evidence')
  }
  return res.json()
}

/**
 * Get all evidence for a task
 */
export async function fetchTaskEvidence(
  projectId: string,
  taskId: string,
  evidenceType?: EvidenceType,
): Promise<EvidenceListResponse> {
  const params = new URLSearchParams()
  if (evidenceType) params.append('evidence_type', evidenceType)

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/evidence?${params}`,
  )
  if (!res.ok) {
    throw new Error('Failed to fetch task evidence')
  }
  return res.json()
}

/**
 * Get all evidence for an explorer entry
 */
export async function fetchEntryEvidence(
  projectId: string,
  entryId: number,
  evidenceType?: EvidenceType,
): Promise<EvidenceListResponse> {
  const params = new URLSearchParams()
  if (evidenceType) params.append('evidence_type', evidenceType)

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/explorer/${entryId}/evidence?${params}`,
  )
  if (!res.ok) {
    throw new Error('Failed to fetch entry evidence')
  }
  return res.json()
}

/**
 * Capture new evidence
 */
export async function captureEvidence(
  projectId: string,
  request: CaptureRequest,
): Promise<CaptureResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/evidence/capture`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url: request.url,
      task_id: request.taskId,
      explorer_entry_id: request.explorerEntryId,
      evidence_type: request.evidenceType || 'screenshot',
      criterion_db_id: request.criterionDbId,
      environment: request.environment || 'local',
      viewport_name: request.viewportName,
    }),
    errorMessage: 'Failed to capture evidence',
  })
}

/**
 * Submit user review for evidence
 */
export async function submitEvidenceReview(
  projectId: string,
  evidenceId: string,
  approved: boolean | null,
  notes?: string,
): Promise<{ success: boolean }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/evidence/${evidenceId}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, notes }),
      errorMessage: 'Failed to submit review',
    },
  )
}

/**
 * Update mockup status
 */
export async function updateMockupStatus(
  projectId: string,
  evidenceId: string,
  status: MockupStatus,
): Promise<{ success: boolean; evidenceId: string; mockupStatus: string }> {
  const params = new URLSearchParams({ status })
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}/mockup-status?${params}`,
    { method: 'PATCH' },
  )
  if (!res.ok) {
    throw new Error('Failed to update mockup status')
  }
  return res.json()
}

/** Mockup list response */
export interface MockupListResponse {
  mockups: EvidenceRecord[]
  total: number
}

/** Mockup comparison response */
export interface MockupComparisonResponse {
  mockup: EvidenceRecord
  actualScreenshot: EvidenceRecord | null
}

/**
 * Get all mockups for an explorer entry
 */
export async function fetchEntryMockups(
  projectId: string,
  entryId: number,
  status?: MockupStatus,
): Promise<MockupListResponse> {
  const params = new URLSearchParams()
  if (status) params.append('status', status)

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/explorer/${entryId}/mockups?${params}`,
  )
  if (!res.ok) {
    throw new Error('Failed to fetch mockups')
  }
  return res.json()
}

/**
 * Get mockup comparison (approved mockup + linked actual screenshot)
 */
export async function fetchMockupComparison(
  projectId: string,
  entryId: number,
): Promise<MockupComparisonResponse> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/explorer/${entryId}/mockups/comparison`,
  )
  if (!res.ok) {
    if (res.status === 404) throw new Error('No approved mockup found')
    throw new Error('Failed to fetch mockup comparison')
  }
  return res.json()
}

/**
 * Get screenshot URL for evidence
 */
export function getScreenshotUrl(
  projectId: string,
  evidenceId: string,
): string {
  return `${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}/screenshot`
}

/**
 * Get evidence summary statistics
 */
export async function fetchEvidenceSummary(
  projectId: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/summary`,
  )
  if (!res.ok) {
    throw new Error('Failed to fetch evidence summary')
  }
  return res.json()
}

/**
 * Get valid evidence types
 */
export async function fetchEvidenceTypes(): Promise<{ types: EvidenceType[] }> {
  const res = await fetch(`${getApiBase()}/api/projects/_/evidence/types`)
  if (!res.ok) {
    throw new Error('Failed to fetch evidence types')
  }
  return res.json()
}
