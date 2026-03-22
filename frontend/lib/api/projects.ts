/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, and agent configuration.
 * Re-exports automation and type definitions for backward compatibility.
 */

import { fetchWithErrorHandling, patchJson, postJson } from './utils'
import type {
  Project,
  ProjectHealth,
  ProjectServicesResponse,
  ProjectUpdate,
  ProjectsWithStatsResponse,
  QualityGateHealth,
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
  root_path?: string
}): Promise<Project> {
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

export async function fetchProjectServices(
  id: string,
): Promise<ProjectServicesResponse> {
  return fetchWithErrorHandling(`/api/projects/${id}/services`, {
    errorMessage: 'Failed to fetch project services',
  })
}

export async function fetchQualityGateHealth(
  id: string,
): Promise<QualityGateHealth> {
  return fetchWithErrorHandling(`/api/projects/${id}/quality/health`, {
    errorMessage: 'Failed to fetch quality gate health',
  })
}

