/**
 * Tasks API - Enrichment & Refinement Workflow
 */

import { fetchWithErrorHandling } from './utils'
import type {
  Task,
  EnrichmentRequest,
  CleanupPromptResponse,
  DiscussionResponse,
  SubtasksResponse,
  Subtask,
  Step,
  StepSummary,
  TaskAcceptanceCriterion,
  CriterionVerifyResponse,
} from './tasks-types'

// ============================================================================
// Enrichment Workflow
// ============================================================================

/**
 * Enrich a task with AI-generated objective, criteria, and subtasks.
 * @param sync If true, runs enrichment synchronously and returns enriched task.
 *             If false (default), queues enrichment and returns task with status 'enriching'.
 */
export async function enrichTask(
  projectId: string,
  request: EnrichmentRequest,
  sync = false,
): Promise<Task> {
  const url = `/api/projects/${projectId}/tasks/enrich${sync ? '?sync=true' : ''}`
  return fetchWithErrorHandling(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    errorMessage: 'Failed to enrich task',
  })
}

/**
 * Clean up and refine a raw task prompt using AI.
 */
export async function cleanupPrompt(
  projectId: string,
  rawRequest: string,
): Promise<CleanupPromptResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/cleanup-prompt`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_request: rawRequest }),
      errorMessage: 'Failed to cleanup prompt',
    },
  )
}

/**
 * Send a message to discuss and refine a task with the AI.
 */
export async function discussTask(
  projectId: string,
  taskId: string,
  message: string,
): Promise<DiscussionResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/discuss`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      errorMessage: 'Failed to discuss task',
    },
  )
}

/**
 * Accept an enriched task, moving it to 'pending' status for execution.
 */
export async function acceptTask(
  projectId: string,
  taskId: string,
): Promise<Task> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/accept`,
    {
      method: 'POST',
      errorMessage: 'Failed to accept task',
    },
  )
}

// ============================================================================
// Subtasks
// ============================================================================

/**
 * Get subtasks for a task.
 */
export async function getSubtasks(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks`,
    {
      errorMessage: 'Failed to fetch subtasks',
    },
  )
}

/**
 * Get subtasks with steps included.
 */
export async function getSubtasksWithSteps(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks?include_steps=true`,
    {
      errorMessage: 'Failed to fetch subtasks with steps',
    },
  )
}

/**
 * Update a subtask's passes status.
 */
export async function updateSubtask(
  projectId: string,
  taskId: string,
  subtaskId: string,
  passes: boolean,
): Promise<Subtask> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passes }),
      errorMessage: 'Failed to update subtask',
    },
  )
}

// ============================================================================
// Steps
// ============================================================================

/**
 * Get steps for a subtask from the normalized table.
 */
export async function getSteps(
  projectId: string,
  taskId: string,
  subtaskId: string,
): Promise<Step[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps`,
    {
      errorMessage: 'Failed to fetch steps',
    },
  )
}

/**
 * Update a step's passes status.
 */
export async function updateStep(
  projectId: string,
  taskId: string,
  subtaskId: string,
  stepNumber: number,
  passes: boolean,
): Promise<Step> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps/${stepNumber}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passes }),
      errorMessage: 'Failed to update step',
    },
  )
}

/**
 * Get step completion summary for a subtask.
 */
export async function getStepSummary(
  projectId: string,
  taskId: string,
  subtaskId: string,
): Promise<StepSummary> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps/summary`,
    {
      errorMessage: 'Failed to fetch step summary',
    },
  )
}

// ============================================================================
// Acceptance Criteria
// ============================================================================

/**
 * Get all acceptance criteria for a task.
 */
export async function getTaskCriteria(
  projectId: string,
  taskId: string,
): Promise<TaskAcceptanceCriterion[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/criteria`,
    {
      errorMessage: 'Failed to fetch task criteria',
    },
  )
}

/**
 * Verify (mark as passed/failed) a task criterion.
 */
export async function verifyTaskCriterion(
  projectId: string,
  taskId: string,
  criterionId: string,
  verifiedBy: 'test' | 'opus' | 'human' | 'agent' = 'human',
  verified: boolean = true,
): Promise<CriterionVerifyResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/criteria/${criterionId}/verify`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verified, verified_by: verifiedBy }),
      errorMessage: 'Failed to verify criterion',
    },
  )
}
