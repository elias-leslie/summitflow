/**
 * Project automation API functions
 *
 * Handles autonomous execution settings for orchestrator task execution.
 */

import type {
  AutonomousExecutionSettings,
  AutonomousExecutionSettingsUpdate,
  RoutineUpkeepRunResult,
  RoutineUpkeepStatus,
} from './projects-types'
import { fetchWithErrorHandling, patchJson, postJson } from './utils'

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

export async function getRoutineUpkeepStatus(
  projectId: string,
): Promise<RoutineUpkeepStatus> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/autonomous/upkeep/status`, {
    errorMessage: 'Failed to fetch routine upkeep status',
  })
}

export async function runRoutineUpkeep(
  projectId: string,
): Promise<RoutineUpkeepRunResult> {
  return postJson(
    `/api/projects/${projectId}/autonomous/upkeep/run`,
    {},
    'Failed to run routine upkeep',
  )
}
