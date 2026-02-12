/**
 * Project automation API functions
 *
 * Handles automation settings for crowdsourced idea processing and
 * autonomous execution settings for orchestrator task execution.
 */

import { fetchWithErrorHandling } from './utils'
import type {
  AutomationSettings,
  ExecuteNowResponse,
  AutonomousExecutionSettings,
  AutonomousExecutionSettingsUpdate,
} from './projects-types'

// ============================================================================
// Automation Settings (for crowdsourced idea processing)
// ============================================================================

export async function getAutomationSettings(
  projectId: string,
): Promise<AutomationSettings> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/settings/automation`,
    {
      errorMessage: 'Failed to fetch automation settings',
    },
  )
}

export async function updateAutomationSettings(
  projectId: string,
  settings: Partial<AutomationSettings>,
): Promise<AutomationSettings> {
  // Fetch current settings first to merge
  const current = await getAutomationSettings(projectId)
  const merged = { ...current, ...settings }

  const res = await fetch(`/api/projects/${projectId}/settings/automation`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(merged),
  })
  if (!res.ok) throw new Error('Failed to update automation settings')
  return res.json()
}

// ============================================================================
// Execute Now (manual trigger for crowdsourced idea processing)
// ============================================================================

export async function executeIdeasNow(
  projectId: string,
): Promise<ExecuteNowResponse> {
  const res = await fetch(`/api/projects/${projectId}/ideas/execute-now`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    if (res.status === 429) {
      const data = await res.json()
      throw new Error(data.detail || 'Too many requests')
    }
    throw new Error('Failed to execute ideas')
  }
  return res.json()
}

// ============================================================================
// Autonomous Execution Settings (for orchestrator task execution)
// ============================================================================

export async function getAutonomousSettings(
  projectId: string,
): Promise<AutonomousExecutionSettings> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/autonomous/settings`,
    {
      errorMessage: 'Failed to fetch autonomous settings',
    },
  )
}

export async function updateAutonomousSettings(
  projectId: string,
  settings: AutonomousExecutionSettingsUpdate,
): Promise<AutonomousExecutionSettings> {
  const res = await fetch(`/api/projects/${projectId}/autonomous/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!res.ok) throw new Error('Failed to update autonomous settings')
  return res.json()
}
