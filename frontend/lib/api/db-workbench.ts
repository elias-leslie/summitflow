import { fetchWithErrorHandling, postJson } from './utils'

export interface DbWorkbenchStatus {
  project_id: string
  running: boolean
  installed: boolean
  configured: boolean
  readonly: boolean
  pid: number | null
  port: number | null
  proxy_url: string
  direct_url: string | null
  shared_with: string | null
  started_at: string | null
  message: string | null
}

export interface DbWorkbenchTarget {
  id: string
  label: string
  database: string | null
  configured: boolean
  source: string
  shared_with: string | null
}

interface DbWorkbenchTargetsResponse {
  targets: DbWorkbenchTarget[]
}

export function fetchDbWorkbenchTargets(): Promise<DbWorkbenchTarget[]> {
  return fetchWithErrorHandling<DbWorkbenchTargetsResponse>(
    '/api/projects/db-workbench/targets',
    { errorMessage: 'Failed to fetch database workbench targets' },
  ).then((response) => response.targets)
}

export function fetchDbWorkbenchStatus(
  projectId: string,
): Promise<DbWorkbenchStatus> {
  return fetchWithErrorHandling<DbWorkbenchStatus>(
    `/api/projects/${projectId}/db-workbench/status`,
    { errorMessage: 'Failed to fetch database workbench status' },
  )
}

export function startDbWorkbench(
  projectId: string,
  readonly = true,
): Promise<DbWorkbenchStatus> {
  return postJson<DbWorkbenchStatus>(
    `/api/projects/${projectId}/db-workbench/start`,
    { readonly },
    'Failed to start database workbench',
  )
}

export function stopDbWorkbench(projectId: string): Promise<DbWorkbenchStatus> {
  return postJson<DbWorkbenchStatus>(
    `/api/projects/${projectId}/db-workbench/stop`,
    {},
    'Failed to stop database workbench',
  )
}
