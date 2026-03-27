export const QUERY_KEYS = {
  projects: ['projects'] as const,
  projectsWithStats: ['projects-with-stats'] as const,
}

export const ROUTE_PROJECT = (id: string) => `/projects/${id}`
export const ROUTE_HOME = '/'

export const DEFAULT_PERMISSION_TIER = 'read'
export const EXECUTION_START_HOUR = 0
export const EXECUTION_END_HOUR = 24
