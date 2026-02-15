/**
 * Project automation API functions
 *
 * Handles autonomous execution settings for orchestrator task execution.
 */

import type {
  AutonomousExecutionSettings,
  AutonomousExecutionSettingsUpdate,
} from './projects-types'

// ============================================================================
// Autonomous Execution Settings (for orchestrator task execution)
// ============================================================================

export async function getAutonomousSettings(
  projectId: string,
): Promise<AutonomousExecutionSettings> {
  const res = await fetch(`/api/projects/${projectId}/autonomous/settings`)
  if (!res.ok) throw new Error('Failed to fetch autonomous settings')
  return res.json()
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
