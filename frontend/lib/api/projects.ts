/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, and agent configuration.
 * Re-exports automation and type definitions for backward compatibility.
 */

import { fetchWithErrorHandling } from './utils'
import type {
  Project,
  ProjectHealth,
  ProjectsWithStatsResponse,
  QualityGateHealth,
  ProjectAgentConfig,
  ProjectAgentConfigUpdate,
} from './projects-types'

// Re-export all types for backward compatibility
export * from './projects-types'

// Re-export all automation functions for backward compatibility
export * from './projects-automation'

// ============================================================================
// Core Project CRUD Operations
// ============================================================================

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
// Health Check Operations
// ============================================================================

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

// ============================================================================
// Agent Configuration
// ============================================================================

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
  return fetchWithErrorHandling(`/api/projects/${projectId}/agents`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
    errorMessage: 'Failed to update agent config',
  })
}
