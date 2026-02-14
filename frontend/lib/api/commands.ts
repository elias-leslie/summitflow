/**
 * Commands API client — sends natural language commands to Agent Hub.
 */

import { fetchJsonWithTimeout } from './utils'
import { getApiBaseUrl } from '../api-config'

export interface CommandResponse {
  response: string
  success: boolean
}

/**
 * Execute a natural language command via the backend.
 * Routes through Agent Hub's completion API.
 */
export async function executeCommand(
  text: string,
  projectId: string = 'summitflow',
  agent: string = 'coder',
): Promise<CommandResponse> {
  const base = getApiBaseUrl()
  return fetchJsonWithTimeout<CommandResponse>(`${base}/api/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, project_id: projectId, agent }),
    errorMessage: 'Command execution failed',
    timeoutMs: 130000, // Commands can take up to 2 minutes
  })
}
