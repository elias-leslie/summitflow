import type {
  DesignAsset,
  DesignAssetComment,
  DesignAssetListResponse,
  DesignAssetStats,
} from './design-assets'
import type {
  Mockup,
  MockupComment,
  MockupFilters,
  MockupListResponse,
  MockupStats,
} from './mockups'
import {
  buildQueryString,
  deleteJson,
  fetchWithErrorHandling,
  postJson,
  putJson,
} from './utils'

export interface ViewerProject {
  id: string
  name: string
  public_url?: string | null
  created_at?: string | null
  sections: string[]
}

export function fetchViewerProjects(): Promise<ViewerProject[]> {
  return fetchWithErrorHandling<ViewerProject[]>('/api/viewer/projects', {
    errorMessage: 'Failed to fetch shared projects',
  })
}

export function fetchViewerMockups(
  projectId: string,
  filters: MockupFilters = {},
): Promise<MockupListResponse> {
  const query = buildQueryString({
    limit: filters.limit,
    offset: filters.offset,
    mockup_type: filters.mockup_type,
    status: filters.status,
    task_id: filters.task_id,
    page_path: filters.page_path,
    generator: filters.generator,
    search: filters.search,
    sort_by: filters.sort_by,
  })
  return fetchWithErrorHandling<MockupListResponse>(
    `/api/viewer/projects/${projectId}/mockups${query}`,
    { errorMessage: 'Failed to fetch shared mockups' },
  )
}

export function fetchViewerMockupStats(
  projectId: string,
): Promise<MockupStats> {
  return fetchWithErrorHandling<MockupStats>(
    `/api/viewer/projects/${projectId}/mockups/stats`,
    { errorMessage: 'Failed to fetch shared mockup stats' },
  )
}

export function fetchViewerMockupHistory(
  projectId: string,
  mockupId: string,
): Promise<Mockup[]> {
  return fetchWithErrorHandling<Mockup[]>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/history`,
    { errorMessage: 'Failed to fetch shared mockup history' },
  )
}

export function getViewerMockupImageUrl(
  projectId: string,
  mockupId: string,
): string {
  return `/api/viewer/projects/${projectId}/mockups/${mockupId}/image`
}

export function getViewerScreenshotUrl(
  projectId: string,
  mockupId: string,
): string {
  return `/api/viewer/projects/${projectId}/mockups/${mockupId}/screenshot`
}

export function rateViewerMockup(
  projectId: string,
  mockupId: string,
  rating: number,
): Promise<Mockup> {
  return postJson<Mockup>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/rating`,
    { rating },
    'Failed to rate shared mockup',
  )
}

export function fetchViewerMockupComments(
  projectId: string,
  mockupId: string,
): Promise<MockupComment[]> {
  return fetchWithErrorHandling<MockupComment[]>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/comments`,
    { errorMessage: 'Failed to fetch shared mockup comments' },
  )
}

export function addViewerMockupComment(
  projectId: string,
  mockupId: string,
  body: string,
): Promise<MockupComment> {
  return postJson<MockupComment>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/comments`,
    { body },
    'Failed to add shared mockup comment',
  )
}

export function updateViewerMockupComment(
  projectId: string,
  mockupId: string,
  commentId: number,
  body: string,
): Promise<MockupComment> {
  return putJson<MockupComment>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/comments/${commentId}`,
    { body },
    'Failed to update shared mockup comment',
  )
}

export function deleteViewerMockupComment(
  projectId: string,
  mockupId: string,
  commentId: number,
): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(
    `/api/viewer/projects/${projectId}/mockups/${mockupId}/comments/${commentId}`,
    'Failed to delete shared mockup comment',
  )
}

export interface ViewerDesignAssetFilters {
  limit?: number
  offset?: number
  asset_type?: string
  workflow?: string
  status?: string
  search?: string
  tag?: string
  sort_by?: string
}

export function fetchViewerDesignAssets(
  projectId: string,
  filters: ViewerDesignAssetFilters = {},
): Promise<DesignAssetListResponse> {
  const query = buildQueryString({
    limit: filters.limit,
    offset: filters.offset,
    asset_type: filters.asset_type,
    workflow: filters.workflow,
    status: filters.status,
    search: filters.search,
    tag: filters.tag,
    sort_by: filters.sort_by,
  })
  return fetchWithErrorHandling<DesignAssetListResponse>(
    `/api/viewer/projects/${projectId}/design-assets${query}`,
    { errorMessage: 'Failed to fetch shared design assets' },
  )
}

export function fetchViewerDesignAssetStats(
  projectId: string,
): Promise<DesignAssetStats> {
  return fetchWithErrorHandling<DesignAssetStats>(
    `/api/viewer/projects/${projectId}/design-assets/stats`,
    { errorMessage: 'Failed to fetch shared design asset stats' },
  )
}

export function fetchViewerDesignAsset(
  projectId: string,
  assetId: string,
): Promise<DesignAsset> {
  return fetchWithErrorHandling<DesignAsset>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}`,
    { errorMessage: 'Failed to fetch shared design asset' },
  )
}

export function getViewerDesignAssetImageUrl(
  projectId: string,
  assetId: string,
): string {
  return `/api/viewer/projects/${projectId}/design-assets/${assetId}/image`
}

export function rateViewerDesignAsset(
  projectId: string,
  assetId: string,
  rating: number,
): Promise<DesignAsset> {
  return postJson<DesignAsset>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/rating`,
    { rating },
    'Failed to rate shared design asset',
  )
}

export function fetchViewerDesignAssetComments(
  projectId: string,
  assetId: string,
): Promise<DesignAssetComment[]> {
  return fetchWithErrorHandling<DesignAssetComment[]>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/comments`,
    { errorMessage: 'Failed to fetch shared asset comments' },
  )
}

export function addViewerDesignAssetComment(
  projectId: string,
  assetId: string,
  body: string,
): Promise<DesignAssetComment> {
  return postJson<DesignAssetComment>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/comments`,
    { body },
    'Failed to add shared asset comment',
  )
}

export function updateViewerDesignAssetComment(
  projectId: string,
  assetId: string,
  commentId: number,
  body: string,
): Promise<DesignAssetComment> {
  return putJson<DesignAssetComment>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/comments/${commentId}`,
    { body },
    'Failed to update shared asset comment',
  )
}

export function deleteViewerDesignAssetComment(
  projectId: string,
  assetId: string,
  commentId: number,
): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/comments/${commentId}`,
    'Failed to delete shared asset comment',
  )
}
