/**
 * Mockups API module
 */

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
  const url = `/api/projects/${projectId}/mockups${queryString ? `?${queryString}` : ''}`

  return fetchWithErrorHandling<MockupListResponse>(url, {
    errorMessage: 'Failed to fetch mockups',
  })
}

/**
 * Fetch mockup stats
 */
export async function fetchMockupStats(
  projectId: string,
): Promise<MockupStats> {
  return fetchWithErrorHandling<MockupStats>(
    `/api/projects/${projectId}/mockups/stats`,
    { errorMessage: 'Failed to fetch mockup stats' },
  )
}

/**
 * Fetch single mockup by ID
 */
export async function fetchMockup(
  projectId: string,
  mockupId: string,
): Promise<Mockup> {
  return fetchWithErrorHandling<Mockup>(
    `/api/projects/${projectId}/mockups/${mockupId}`,
    { errorMessage: 'Failed to fetch mockup' },
  )
}

/**
 * Fetch mockup iteration history
 */
export async function fetchMockupHistory(
  projectId: string,
  mockupId: string,
): Promise<Mockup[]> {
  return fetchWithErrorHandling<Mockup[]>(
    `/api/projects/${projectId}/mockups/${mockupId}/history`,
    { errorMessage: 'Failed to fetch mockup history' },
  )
}

/**
 * Create a new mockup
 */
export async function createMockup(
  projectId: string,
  data: MockupCreateRequest,
): Promise<Mockup> {
  return fetchWithErrorHandling<Mockup>(`/api/projects/${projectId}/mockups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    errorMessage: 'Failed to create mockup',
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
  return fetchWithErrorHandling<Mockup>(
    `/api/projects/${projectId}/mockups/${mockupId}/status`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, approved_by: approvedBy }),
      errorMessage: 'Failed to update mockup status',
    },
  )
}

/**
 * Delete a mockup
 */
export async function deleteMockup(
  projectId: string,
  mockupId: string,
): Promise<{ deleted: boolean }> {
  return fetchWithErrorHandling<{ deleted: boolean }>(
    `/api/projects/${projectId}/mockups/${mockupId}`,
    {
      method: 'DELETE',
      errorMessage: 'Failed to delete mockup',
    },
  )
}

/**
 * Get the URL for a mockup's image
 */
export function getMockupImageUrl(projectId: string, mockupId: string): string {
  return `/api/projects/${projectId}/mockups/${mockupId}/image`
}

/**
 * Get the URL for a mockup's original screenshot.
 * Only available for design-analyzer mockups.
 */
export function getScreenshotUrl(projectId: string, mockupId: string): string {
  return `/api/projects/${projectId}/mockups/${mockupId}/screenshot`
}

/**
 * Check if a mockup has an available screenshot.
 * Returns true if the mockup was generated by design-analyzer.
 */
export function hasScreenshot(mockup: Mockup): boolean {
  return mockup.generator === 'design-analyzer'
}

/**
 * Analyze page design response
 */
export interface AnalyzePageResponse {
  success: boolean
  mockup_id: string | null
  screenshot_path: string | null
  mockup_image_path: string | null
  recommendations: string | null
  issues_found: number
  error: string | null
  generation_time_ms: number
}

/**
 * Analyze a page's design and generate improvement recommendations
 */
export async function analyzePage(
  projectId: string,
  pageUrl: string,
  pagePath?: string,
): Promise<AnalyzePageResponse> {
  return fetchWithErrorHandling<AnalyzePageResponse>(
    `/api/projects/${projectId}/mockups/analyze-page`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_url: pageUrl, page_path: pagePath }),
      errorMessage: 'Failed to analyze page design',
    },
  )
}
