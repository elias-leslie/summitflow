/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, page discovery, and agent
 * configuration.
 * Re-exports type definitions for backward compatibility.
 */

import type {
  Project,
  ProjectCreate,
  ProjectHealth,
  ProjectPage,
  ProjectPagesResponse,
  ProjectReadme,
  ProjectRegistrationDefaults,
  ProjectsWithStatsResponse,
  ProjectUpdate,
} from './projects-types'
import { fetchWithErrorHandling, patchJson, postJson } from './utils'

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

export async function fetchProjectReadme(id: string): Promise<ProjectReadme> {
  const data = await fetchWithErrorHandling<unknown>(
    `/api/projects/${id}/readme`,
    { errorMessage: 'Failed to load README.md' },
  )
  if (!data || typeof data !== 'object') {
    throw new Error('Invalid README response')
  }
  const readme = data as Record<string, unknown>
  if (readme.project_id !== id) throw new Error('Invalid README response')
  if (readme.status === 'available' && typeof readme.content === 'string') {
    return { project_id: id, status: 'available', content: readme.content }
  }
  if (
    (readme.status === 'missing' || readme.status === 'unavailable') &&
    readme.content === null
  ) {
    return { project_id: id, status: readme.status, content: null }
  }
  throw new Error('Invalid README response')
}

export async function fetchProjectRegistrationDefaults(): Promise<ProjectRegistrationDefaults> {
  return fetchWithErrorHandling('/api/projects/registration-defaults', {
    errorMessage: 'Failed to load project defaults',
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

// ============================================================================
// Page Discovery
// ============================================================================

/** List the project's pages, discovered live from its frontend routes. */
export async function fetchProjectPages(id: string): Promise<ProjectPage[]> {
  const data = await fetchWithErrorHandling<ProjectPagesResponse>(
    `/api/projects/${id}/pages`,
    { errorMessage: 'Failed to fetch project pages' },
  )
  return data.items
}

/** Resolve a page to the URL to open: explicit url, else localhost:port + path. */
export function buildPageUrl(page: ProjectPage): string {
  if (page.url) return page.url
  return page.port ? `http://localhost:${page.port}${page.path}` : page.path
}
