// API module re-exports
// All domain-specific API functions are now in separate modules under lib/api/

// Re-export domain modules
export * from './api/backups'
export * from './api/files'
export * from './api/git'
export * from './api/notifications'
export * from './api/projects'
export * from './api/tasks'

// Re-export utilities for consumers that need them directly
export {
  buildQueryString,
  fetchWithErrorHandling,
} from './api/utils'

// Re-export API base URL helper for callers that need it
export { getApiBaseUrl } from './api-config'
