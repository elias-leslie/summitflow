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
  code_node_count: number
  rationale_node_count: number
  semantic_node_count: number
  file_type_counts: Record<string, number>
  detected_source_counts: Record<string, number>
  semantic_source_count: number
  semantic_coverage: string
  graph_stale: boolean
  changed_files_since_graph: number
  changed_files_sample: string[]
  graph_size_bytes: number
  html_size_bytes: number
  report_size_bytes: number
  html_uses_cdn: boolean
  diagnostics: string[]
  unreadable_error: string | null
}

export interface GraphifyUpdateResponse extends GraphifyStatus {
  output: string
}

export interface GraphifyCommandResponse {
  command: string[]
  output: string
  elapsed_ms: number
  output_chars: number
  estimated_tokens: number
}

export type GraphifyCommandMode = 'query' | 'path' | 'explain'

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

export function runGraphifyQuery(
  projectId: string,
  question: string,
  budget = 1200,
  dfs = false,
): Promise<GraphifyCommandResponse> {
  return postJson(
    `/api/projects/${projectId}/graphify/query`,
    { question, budget, dfs },
    'Failed to query graph',
  )
}

export function runGraphifyPath(
  projectId: string,
  source: string,
  target: string,
): Promise<GraphifyCommandResponse> {
  return postJson(
    `/api/projects/${projectId}/graphify/path`,
    { source, target },
    'Failed to find graph path',
  )
}

export function runGraphifyExplain(
  projectId: string,
  node: string,
): Promise<GraphifyCommandResponse> {
  return postJson(
    `/api/projects/${projectId}/graphify/explain`,
    { node },
    'Failed to explain graph node',
  )
}
