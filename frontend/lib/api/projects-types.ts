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
  root_path?: string
  daily_cost_budget_usd?: number
  monthly_cost_budget_usd?: number
  budget_alert_threshold?: number
}

// Onboarding writes the project's .index.yaml; it takes no options.
export type ProjectOnboardingRequest = Record<string, never>

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
  active_checkpoint?: import('./checkpoints').Checkpoint
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
  endpoint?: string
  status_code?: number
  response_time_ms?: number
  error?: string
  checked_at: string
}

export type ProjectReadme =
  | { project_id: string; status: 'available'; content: string }
  | { project_id: string; status: 'missing' | 'unavailable'; content: null }

/** A page discovered live from the project's frontend routes. */
export interface ProjectPage {
  path: string
  name: string
  url: string | null
  port: number | null
}

export interface ProjectRegistrationDefaults {
  managed_projects_root: string
}

export interface ProjectPagesResponse {
  items: ProjectPage[]
}
