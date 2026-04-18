/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, and agent configuration.
 * Re-exports automation and type definitions for backward compatibility.
 */

import type {
  FetchQualityResultsOptions,
  Project,
  ProjectCreate,
  ProjectHealth,
  ProjectsWithStatsResponse,
  ProjectUpdate,
  QualityCheckResultsResponse,
  QualityGateHealth,
} from './projects-types'
import {
  buildQueryString,
  fetchWithErrorHandling,
  patchJson,
  postJson,
} from './utils'

// Re-export all automation functions for backward compatibility
export * from './projects-automation'
// Re-export all types for backward compatibility
export * from './projects-types'

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

export async function createProject(project: ProjectCreate): Promise<Project> {
  return postJson('/api/projects', project, 'Failed to create project')
}

export async function updateProject(
  id: string,
  project: ProjectUpdate,
): Promise<Project> {
  return patchJson(`/api/projects/${id}`, project, 'Failed to update project')
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

export async function fetchQualityResults(
  id: string,
  options: FetchQualityResultsOptions = {},
): Promise<QualityCheckResultsResponse> {
  const query = buildQueryString({
    check_type: options.check_type,
    status: options.status,
    unfixed_only: options.unfixed_only ? 'true' : undefined,
    limit: options.limit ?? 100,
    offset: options.offset,
  })

  return fetchWithErrorHandling(`/api/projects/${id}/quality/results${query}`, {
    errorMessage: 'Failed to fetch quality results',
  })
}
