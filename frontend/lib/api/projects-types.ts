/**
 * Project type definitions
 *
 * Shared types for projects, health checks, and configuration.
 */

export interface Project {
  id: string
  name: string
  base_url: string
  health_endpoint: string
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

export interface ProjectCreate {
  id: string
  name: string
  base_url: string
  health_endpoint?: string
  root_path?: string
  agent_hub_permission?: ProjectPermissionBootstrap
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

export interface ProjectUpdate {
  name?: string
  base_url?: string
  health_endpoint?: string
  root_path?: string
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


export interface AutonomousExecutionSettings {
  // Access control (enabled, hours) now managed by Agent Hub project permissions.
  // See: agent.summitflow.dev/access-control/permissions
  frequency_minutes: number
  auto_merge_tiers: number[]
  task_types: string[]
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
