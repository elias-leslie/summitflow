/**
 * Mockups API module
 */

import { buildApiUrl } from '../api-config'
import { fetchWithErrorHandling } from './utils'

export interface Mockup {
  id: number
  project_id: string
  mockup_id: string
  name: string
  description: string | null
  mockup_type: string
  file_path: string | null
  content: string | null
  status: string
  approved_at: string | null
  approved_by: string | null
  applied_at: string | null
  task_id: string | null
  page_path: string | null
  version: number
  parent_mockup_id: number | null
  generator: string | null
  generation_prompt: string | null
  generation_time_ms: number | null
  iteration_count: number
  created_at: string | null
  updated_at: string | null
}

export interface MockupListResponse {
  items: Mockup[]
  total: number
  limit: number
  offset: number
}

export interface MockupStats {
  total: number
  by_status: Record<string, number>
  unique_generators: number
  avg_generation_time_ms: number | null
}

export interface MockupCreateRequest {
  name: string
  description?: string
  mockup_type?: string
  file_path?: string
  content?: string
  task_id?: string
  page_path?: string
  parent_mockup_id?: number
  generator?: string
  generation_prompt?: string
  generation_time_ms?: number
}

export interface MockupFilters {
  limit?: number
  offset?: number
  mockup_type?: string
  status?: string
  task_id?: string
  page_path?: string
  generator?: string
  search?: string
}

/**
 * Fetch mockups list with optional filters
 */
export async function fetchMockups(
  projectId: string,
  filters: MockupFilters = {},
): Promise<MockupListResponse> {
  const params = new URLSearchParams()
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.offset) params.set('offset', String(filters.offset))
  if (filters.mockup_type) params.set('mockup_type', filters.mockup_type)
  if (filters.status) params.set('status', filters.status)
  if (filters.task_id) params.set('task_id', filters.task_id)
  if (filters.page_path) params.set('page_path', filters.page_path)
  if (filters.generator) params.set('generator', filters.generator)
  if (filters.search) params.set('search', filters.search)

  const queryString = params.toString()
  const url = buildApiUrl(
    `/projects/${projectId}/mockups${queryString ? `?${queryString}` : ''}`,
  )

  return fetchWithErrorHandling<MockupListResponse>(url)
}

/**
 * Fetch mockup stats
 */
export async function fetchMockupStats(
  projectId: string,
): Promise<MockupStats> {
  const url = buildApiUrl(`/projects/${projectId}/mockups/stats`)
  return fetchWithErrorHandling<MockupStats>(url)
}

/**
 * Fetch single mockup by ID
 */
export async function fetchMockup(
  projectId: string,
  mockupId: string,
): Promise<Mockup> {
  const url = buildApiUrl(`/projects/${projectId}/mockups/${mockupId}`)
  return fetchWithErrorHandling<Mockup>(url)
}

/**
 * Fetch mockup iteration history
 */
export async function fetchMockupHistory(
  projectId: string,
  mockupId: string,
): Promise<Mockup[]> {
  const url = buildApiUrl(`/projects/${projectId}/mockups/${mockupId}/history`)
  return fetchWithErrorHandling<Mockup[]>(url)
}

/**
 * Create a new mockup
 */
export async function createMockup(
  projectId: string,
  data: MockupCreateRequest,
): Promise<Mockup> {
  const url = buildApiUrl(`/projects/${projectId}/mockups`)
  return fetchWithErrorHandling<Mockup>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

/**
 * Update mockup status
 */
export async function updateMockupStatus(
  projectId: string,
  mockupId: string,
  status: string,
  approvedBy?: string,
): Promise<Mockup> {
  const url = buildApiUrl(`/projects/${projectId}/mockups/${mockupId}/status`)
  return fetchWithErrorHandling<Mockup>(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, approved_by: approvedBy }),
  })
}

/**
 * Delete a mockup
 */
export async function deleteMockup(
  projectId: string,
  mockupId: string,
): Promise<{ deleted: boolean }> {
  const url = buildApiUrl(`/projects/${projectId}/mockups/${mockupId}`)
  return fetchWithErrorHandling<{ deleted: boolean }>(url, {
    method: 'DELETE',
  })
}
