/**
 * Project automation API functions
 *
 * Handles autonomous execution settings for orchestrator task execution.
 */

import type {
  AutonomousExecutionSettings,
  AutonomousExecutionSettingsUpdate,
} from './projects-types'
import { fetchWithErrorHandling } from './utils'

// ============================================================================
// Autonomous Execution Settings (for orchestrator task execution)
// ============================================================================

export async function getAutonomousSettings(
  projectId: string,
): Promise<AutonomousExecutionSettings> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/autonomous/settings`, {
    errorMessage: 'Failed to fetch autonomous settings',
  })
}

export async function updateAutonomousSettings(
  projectId: string,
  settings: AutonomousExecutionSettingsUpdate,
): Promise<AutonomousExecutionSettings> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/autonomous/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
    errorMessage: 'Failed to update autonomous settings',
  })
}
