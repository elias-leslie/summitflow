import type {
  DesignAsset,
  DesignAssetListResponse,
  DesignAssetStats,
} from './design-assets'
import type {
  Mockup,
  MockupFilters,
  MockupListResponse,
  MockupStats,
} from './mockups'
import { buildQueryString, fetchWithErrorHandling, postJson } from './utils'

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

export function voteViewerDesignAsset(
  projectId: string,
  assetId: string,
  vote: 'up' | 'down',
): Promise<DesignAsset> {
  return postJson<DesignAsset>(
    `/api/viewer/projects/${projectId}/design-assets/${assetId}/votes`,
    { vote },
    'Failed to vote on shared design asset',
  )
}
