/**
 * Project type definitions
 *
 * Shared types for projects, health checks, and configuration.
 */

export type ProjectCategory = 'production' | 'testing' | 'dev'

export const PROJECT_CATEGORY_ORDER: ProjectCategory[] = [
  'production',
  'testing',
  'dev',
]

export const PROJECT_CATEGORY_LABELS: Record<ProjectCategory, string> = {
  production: 'Production',
  testing: 'Testing',
  dev: 'Dev',
}

export interface Project {
  id: string
  name: string
  base_url: string
  public_url?: string
  health_endpoint: string
  category: ProjectCategory
  sidebar_rank: number | null
  created_at: string
  health_status?: string
  root_path?: string
}

export interface ProjectPermissionBootstrap {
  permission_tier?: string
  auto_exec_enabled?: boolean
  execution_start_hour?: number
  execution_end_hour?: number
  root_path?: string
  daily_cost_budget_usd?: number
  monthly_cost_budget_usd?: number
  budget_alert_threshold?: number
}

export interface ProjectOnboardingRequest {
  enable_backup_schedule?: boolean
  backup_frequency?: 'daily' | 'weekly' | 'monthly' | 'hourly'
  backup_retention_days?: number
  queue_initial_backup?: boolean
}

export interface ProjectCreate {
  id: string
  name: string
  base_url?: string
  public_url?: string
  health_endpoint?: string
  root_path?: string
  category?: ProjectCategory
  summitflow_hosted?: boolean
  agent_hub_permission?: ProjectPermissionBootstrap
  onboarding?: ProjectOnboardingRequest
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
  public_url?: string
  health_endpoint: string
  root_path?: string
  logo_url?: string
  category: ProjectCategory
  sidebar_rank: number | null
  created_at: string
  health_status?: string
  stats: ProjectStats
}

export interface ProjectUpdate {
  name?: string
  base_url?: string
  public_url?: string
  health_endpoint?: string
  root_path?: string
  category?: ProjectCategory
  sidebar_rank?: number
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

export type QualityCheckType =
  | 'pytest'
  | 'vitest'
  | 'ruff'
  | 'types'
  | 'biome'
  | 'tsc'

export interface QualityCheckResult {
  id: number
  project_id: string
  check_type: string
  check_name: string | null
  status: string
  error_count: number
  warning_count: number
  error_message: string | null
  file_path: string | null
  line_number: number | null
  column_number: number | null
  run_duration_ms: number | null
  git_sha: string | null
  triggered_by: string | null
  fix_attempted: boolean
  fix_attempts: number
  fixed_at: string | null
  fixed_by: string | null
  created_at: string
  updated_at: string
  escalation_task_id: string | null
}

export interface QualityCheckResultsResponse {
  items: QualityCheckResult[]
  total: number
  unfixed_count: number
}

export interface FetchQualityResultsOptions {
  check_type?: QualityCheckType
  status?: 'pass' | 'fail' | 'error' | 'skipped'
  unfixed_only?: boolean
  limit?: number
  offset?: number
}


export interface AutonomousExecutionSettings {
  // Access control (enabled, hours) now managed by Agent Hub project permissions.
  // See: agent.summitflow.dev/access-control/permissions
  frequency_minutes: number
  auto_merge_tiers: number[]
  task_types: string[]
  upkeep_enabled: boolean
  upkeep_frequency_minutes: number
  upkeep_batch_limit: number
  max_concurrent: number
  max_tasks_per_day: number | null
  cooldown_minutes: number
  allowed_types: string[] | null
  max_self_fix_attempts: number
  max_supervisor_attempts: number
  max_extensions: number
  auto_merge_enabled: boolean
  require_review: boolean
  quality_gate_tools: string[]
  quality_gate_mode: string
  quality_gate_fix_enabled: boolean
}

export interface AutonomousExecutionSettingsUpdate {
  frequency_minutes?: number
  auto_merge_tiers?: number[]
  task_types?: string[]
  upkeep_enabled?: boolean
  upkeep_frequency_minutes?: number
  upkeep_batch_limit?: number
  max_concurrent?: number
  max_tasks_per_day?: number | null
  cooldown_minutes?: number
  allowed_types?: string[] | null
  max_self_fix_attempts?: number
  max_supervisor_attempts?: number
  max_extensions?: number
  auto_merge_enabled?: boolean
  require_review?: boolean
  quality_gate_tools?: string[]
  quality_gate_mode?: string
  quality_gate_fix_enabled?: boolean
}

export interface MaintenanceRun {
  id: number
  workflow_name: string
  status: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  rows_cleaned: number
  summary: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export interface RoutineUpkeepStatus {
  settings: {
    enabled: boolean
    frequency_minutes: number
    batch_limit: number
  }
  latest: MaintenanceRun | null
  recent: MaintenanceRun[]
}

export interface RoutineUpkeepRunResult {
  project_id: string
  status: string
  tasks_created: number
  dispatch: Record<string, unknown>
  created_task_ids: string[]
  sources: Record<string, unknown>
  source_errors: Record<string, string>
  reason?: string | null
}
