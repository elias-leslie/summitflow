export const QUERY_KEYS = {
  projects: ['projects'] as const,
  projectsWithStats: ['projects-with-stats'] as const,
}

export const ROUTE_PROJECT = (id: string) => `/projects/${id}`
export const ROUTE_HOME = '/'

export const DEFAULT_PERMISSION_TIER = 'read'
export const EXECUTION_START_HOUR = 0
export const EXECUTION_END_HOUR = 24
export const DEFAULT_ONBOARDING = {
  enable_backup_schedule: true,
  backup_frequency: 'daily',
  backup_retention_days: 30,
  queue_initial_backup: true,
} as const
