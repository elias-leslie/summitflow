// API module re-exports
// All domain-specific API functions are now in separate modules under lib/api/

// Re-export domain modules
export * from './api/backups'
export * from './api/evidence'
export * from './api/extraction'
export * from './api/git'
export * from './api/notifications'
export * from './api/projects'
export * from './api/prompts'
export * from './api/tasks'
export * from './api/tests'

// Re-export utilities for consumers that need them directly
export {
  buildQueryString,
  fetchWithErrorHandling,
  getApiBase,
} from './api/utils'

// Legacy type export for backwards compatibility
export interface AcceptanceCriterion {
  id: string
  criterion: string
  verification: string
  type: string
  passed: boolean | null
  verified_at: string | null
  verification_output: string | null
}
