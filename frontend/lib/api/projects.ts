/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, and agent configuration.
 */

import { fetchWithErrorHandling } from './utils'

export interface Project {
  id: string
  name: string
  base_url: string
  health_endpoint: string
  created_at: string
  health_status?: string
  root_path?: string
}

export interface ProjectStats {
  features: number
  tasks: number
  bugs: number
  blocked: number
}

export interface ProjectWithStats {
  id: string
  name: string
  base_url: string
  health_endpoint: string
  root_path?: string
  logo_url?: string
  created_at: string
  health_status?: string
  stats: ProjectStats
}

export interface ProjectsWithStatsResponse {
  projects: ProjectWithStats[]
  total: number
}

export interface ProjectHealth {
  project_id: string
  healthy: boolean
  status_code?: number
  response_time_ms?: number
  error?: string
  checked_at: string
}

export interface QualityGateHealth {
  project_id: string
  overall_pass: boolean
  total_unfixed: number
  checks: Record<
    string,
    {
      status: string
      error_count: number
      warning_count: number
      unfixed_count: number
    }
  >
}

export interface ProjectAgentConfig {
  claude_enabled: boolean
  gemini_enabled: boolean
  default_agent: string
  claude_model: string
  gemini_model: string
  memory_enabled: boolean
  observations_enabled: boolean
  diary_enabled: boolean
  patterns_enabled: boolean
  checkpoints_enabled: boolean
  context_injection_enabled: boolean
  component_source: string
  // Extraction throttle
  extraction_enabled: boolean
  extraction_rpm_limit: number
}

export interface ProjectAgentConfigUpdate {
  claude_enabled?: boolean
  gemini_enabled?: boolean
  default_agent?: string
  claude_model?: string
  gemini_model?: string
  memory_enabled?: boolean
  observations_enabled?: boolean
  diary_enabled?: boolean
  patterns_enabled?: boolean
  checkpoints_enabled?: boolean
  context_injection_enabled?: boolean
  component_source?: string
  // Extraction throttle
  extraction_enabled?: boolean
  extraction_rpm_limit?: number
}

export async function fetchProjects(): Promise<Project[]> {
  return fetchWithErrorHandling('/api/projects', {
    errorMessage: 'Failed to fetch projects',
  })
}

export async function fetchProjectsWithStats(): Promise<ProjectsWithStatsResponse> {
  return fetchWithErrorHandling('/api/projects/with-stats', {
    errorMessage: 'Failed to fetch projects with stats',
  })
}

export async function fetchProject(id: string): Promise<Project> {
  return fetchWithErrorHandling(`/api/projects/${id}`, {
    errorMessage: 'Failed to fetch project',
  })
}

export async function fetchProjectHealth(id: string): Promise<ProjectHealth> {
  return fetchWithErrorHandling(`/api/projects/${id}/health`, {
    errorMessage: 'Failed to check project health',
  })
}

export async function fetchQualityGateHealth(
  id: string,
): Promise<QualityGateHealth> {
  return fetchWithErrorHandling(`/api/projects/${id}/quality/health`, {
    errorMessage: 'Failed to fetch quality gate health',
  })
}

export async function getAgentConfig(
  projectId: string,
): Promise<ProjectAgentConfig> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/agents`, {
    errorMessage: 'Failed to fetch agent config',
  })
}

export async function updateAgentConfig(
  projectId: string,
  config: ProjectAgentConfigUpdate,
): Promise<ProjectAgentConfig> {
  const res = await fetch(`/api/projects/${projectId}/agents`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error('Failed to update agent config')
  return res.json()
}

export async function createProject(project: {
  id: string
  name: string
  base_url: string
  health_endpoint?: string
}): Promise<Project> {
  return fetchWithErrorHandling('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(project),
    errorMessage: 'Failed to create project',
  })
}

// ============================================================================
// Automation Settings (for crowdsourced idea processing)
// ============================================================================

export interface AutomationSettings {
  schedule_preset: 'nightly' | 'weekly' | 'monthly'
  cron_expression: string
  daily_budget_usd: number
  primary_agent: 'claude' | 'gemini'
  secondary_agent: 'claude' | 'gemini'
  enabled: boolean
}

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

export interface ExecuteNowResponse {
  status: string
  task_id: string
  project_id: string
  message: string
}

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

export interface AutonomousExecutionSettings {
  enabled: boolean
  frequency_minutes: number
  auto_merge_tiers: number[]
  task_types: string[]
  start_hour: number
  end_hour: number
  max_concurrent: number
  max_tasks_per_day: number | null
  cooldown_minutes: number
  allowed_types: string[] | null
  preferred_model_tier: string
  max_self_fix_attempts: number
  max_supervisor_attempts: number
  max_extensions: number
  auto_merge_enabled: boolean
  require_review: boolean
}

export interface AutonomousExecutionSettingsUpdate {
  enabled?: boolean
  frequency_minutes?: number
  auto_merge_tiers?: number[]
  task_types?: string[]
  start_hour?: number
  end_hour?: number
  max_concurrent?: number
  max_tasks_per_day?: number | null
  cooldown_minutes?: number
  allowed_types?: string[] | null
  preferred_model_tier?: string
  max_self_fix_attempts?: number
  max_supervisor_attempts?: number
  max_extensions?: number
  auto_merge_enabled?: boolean
  require_review?: boolean
}

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
