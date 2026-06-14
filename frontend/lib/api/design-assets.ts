import {
  buildQueryString,
  deleteJson,
  fetchWithErrorHandling,
  postJson,
  putJson,
} from './utils'

export interface DesignAsset {
  id: number
  project_id: string
  asset_id: string
  name: string
  description: string | null
  asset_type: string
  workflow: string
  status: string
  prompt: string
  negative_prompt: string | null
  style_prompt: string | null
  background: string
  width: number
  height: number
  transparent_background: boolean
  model: string | null
  generator: string | null
  file_path: string | null
  source_asset_id: number | null
  sheet_columns: number | null
  sheet_rows: number | null
  frame_width: number | null
  frame_height: number | null
  animation_labels: string[]
  tags: string[]
  metadata: Record<string, unknown>
  approved_at: string | null
  approved_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface DesignAssetListResponse {
  items: DesignAsset[]
  total: number
  limit: number
  offset: number
}

export interface DesignAssetStats {
  total: number
  by_status: Record<string, number>
  by_type: Record<string, number>
  unique_models: number
}

export interface GenerateDesignAssetRequest {
  name: string
  prompt: string
  description?: string
  asset_type?: string
  workflow?: string
  size?: string
  model?: string
  style_prompt?: string
  negative_prompt?: string
  background?: string
  transparent_background?: boolean
  variant_count?: number
  tags?: string[]
  sheet_columns?: number
  sheet_rows?: number
  frame_width?: number
  frame_height?: number
  animation_labels?: string[]
  source_asset_id?: number
}

export interface ImportDesignAssetRequest {
  name: string
  image_base64: string
  mime_type: string
  original_file_name?: string
  prompt?: string
  description?: string
  asset_type?: string
  workflow?: string
  background?: string
  transparent_background?: boolean
  tags?: string[]
  sheet_columns?: number
  sheet_rows?: number
  frame_width?: number
  frame_height?: number
  animation_labels?: string[]
  source_asset_id?: number
  metadata?: Record<string, unknown>
}

export interface GenerateDesignAssetResponse {
  success: boolean
  assets: DesignAsset[]
  generation_time_ms: number
}

export interface DesignAssetExport {
  id: number
  asset_db_id: number
  export_id: string
  export_type: string
  file_path: string
  manifest_path: string | null
  metadata: Record<string, unknown>
  created_at: string | null
}

export async function fetchDesignAssets(
  projectId: string,
  filters: {
    limit?: number
    offset?: number
    asset_type?: string
    workflow?: string
    status?: string
    search?: string
    tag?: string
  } = {},
): Promise<DesignAssetListResponse> {
  const query = buildQueryString(filters)
  return fetchWithErrorHandling<DesignAssetListResponse>(
    `/api/projects/${projectId}/design-assets${query}`,
    { errorMessage: 'Failed to fetch design assets' },
  )
}

export async function fetchDesignAssetStats(
  projectId: string,
): Promise<DesignAssetStats> {
  return fetchWithErrorHandling<DesignAssetStats>(
    `/api/projects/${projectId}/design-assets/stats`,
    { errorMessage: 'Failed to fetch design asset stats' },
  )
}

export async function generateDesignAssets(
  projectId: string,
  data: GenerateDesignAssetRequest,
): Promise<GenerateDesignAssetResponse> {
  return postJson<GenerateDesignAssetResponse>(
    `/api/projects/${projectId}/design-assets/generate`,
    data,
    'Failed to generate design assets',
  )
}

export async function importDesignAsset(
  projectId: string,
  data: ImportDesignAssetRequest,
): Promise<GenerateDesignAssetResponse> {
  return postJson<GenerateDesignAssetResponse>(
    `/api/projects/${projectId}/design-assets/import`,
    data,
    'Failed to import design asset',
  )
}

export async function updateDesignAssetStatus(
  projectId: string,
  assetId: string,
  status: string,
  approvedBy?: string,
): Promise<DesignAsset> {
  return putJson<DesignAsset>(
    `/api/projects/${projectId}/design-assets/${assetId}/status`,
    { status, approved_by: approvedBy },
    'Failed to update asset status',
  )
}

export async function deleteDesignAsset(
  projectId: string,
  assetId: string,
): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(
    `/api/projects/${projectId}/design-assets/${assetId}`,
    'Failed to delete design asset',
  )
}

export async function exportSpriteFrames(
  projectId: string,
  assetId: string,
): Promise<DesignAssetExport> {
  return fetchWithErrorHandling<DesignAssetExport>(
    `/api/projects/${projectId}/design-assets/${assetId}/exports/sprite-frames`,
    {
      method: 'POST',
      errorMessage: 'Failed to export sprite frames',
    },
  )
}

export async function fetchDesignAssetExports(
  projectId: string,
  assetId: string,
): Promise<DesignAssetExport[]> {
  return fetchWithErrorHandling<DesignAssetExport[]>(
    `/api/projects/${projectId}/design-assets/${assetId}/exports`,
    { errorMessage: 'Failed to fetch asset exports' },
  )
}

export function getDesignAssetImageUrl(
  projectId: string,
  assetId: string,
): string {
  return `/api/projects/${projectId}/design-assets/${assetId}/image`
}
