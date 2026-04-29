import { fetchWithErrorHandling, postJson } from './utils'

export interface GraphifyStatus {
  project_id: string
  root_path: string
  graph_exists: boolean
  html_available: boolean
  report_available: boolean
  node_count: number
  edge_count: number
  community_count: number
  graph_updated_at: string | null
  html_updated_at: string | null
  report_updated_at: string | null
  html_url: string | null
  report_url: string | null
}

export interface GraphifyUpdateResponse extends GraphifyStatus {
  output: string
}

export function fetchGraphifyStatus(
  projectId: string,
): Promise<GraphifyStatus> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/graphify/status`, {
    errorMessage: 'Failed to fetch graph status',
  })
}

export function updateGraphify(
  projectId: string,
): Promise<GraphifyUpdateResponse> {
  return postJson(
    `/api/projects/${projectId}/graphify/update`,
    {},
    'Failed to update graph',
  )
}
