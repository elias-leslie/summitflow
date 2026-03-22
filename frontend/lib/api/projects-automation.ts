/**
 * Project automation API functions
 *
 * Handles autonomous execution settings for orchestrator task execution.
 */

import type {
  AutonomousExecutionSettings,
  AutonomousExecutionSettingsUpdate,
} from './projects-types'
import { fetchWithErrorHandling, patchJson } from './utils'

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
  return patchJson(`/api/projects/${projectId}/autonomous/settings`, settings, 'Failed to update autonomous settings')
}
