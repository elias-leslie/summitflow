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
  preferred_model_tier: string
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
  preferred_model_tier?: string
  max_self_fix_attempts?: number
  max_supervisor_attempts?: number
  max_extensions?: number
  auto_merge_enabled?: boolean
  require_review?: boolean
  quality_gate_tools?: string[]
  quality_gate_mode?: string
  quality_gate_fix_enabled?: boolean
}
