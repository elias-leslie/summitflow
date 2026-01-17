/**
 * Prompt API functions
 *
 * Handles prompt CRUD operations, export/import functionality.
 */

import { getApiBase } from './utils'

export type PromptCategory = 'spec' | 'recovery' | 'qa' | 'extraction'

export interface Prompt {
  prompt_type: string
  prompt_text: string
  primary_agent: string
  primary_model: string
  category: PromptCategory
  thinking_budget: number
  tools_enabled: string[]
  is_default: boolean
  created_at: string | null
  updated_at: string | null
}

export interface PromptsExport {
  project_id: string
  exported_at: string
  prompts: Prompt[]
}

export interface PromptUpdate {
  prompt_text: string
  primary_agent?: string
  primary_model?: string
  category?: PromptCategory
  thinking_budget?: number
  tools_enabled?: string[]
}

export async function fetchPrompts(
  projectId: string,
  category?: PromptCategory,
): Promise<Prompt[]> {
  const url = category
    ? `${getApiBase()}/api/projects/${projectId}/prompts?category=${category}`
    : `${getApiBase()}/api/projects/${projectId}/prompts`
  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to fetch prompts')
  return res.json()
}

export async function fetchPrompt(
  projectId: string,
  promptType: string,
): Promise<Prompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`,
  )
  if (!res.ok) throw new Error('Failed to fetch prompt')
  return res.json()
}

export async function updatePrompt(
  projectId: string,
  promptType: string,
  config: PromptUpdate,
): Promise<Prompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    },
  )
  if (!res.ok) throw new Error('Failed to update prompt')
  return res.json()
}

export async function deletePrompt(
  projectId: string,
  promptType: string,
): Promise<{
  deleted: boolean
  reverted_to_default: boolean
  prompt_type: string
}> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`,
    { method: 'DELETE' },
  )
  if (!res.ok) throw new Error('Failed to delete prompt')
  return res.json()
}

export async function exportPrompts(
  projectId: string,
  category?: PromptCategory,
): Promise<PromptsExport> {
  const url = category
    ? `${getApiBase()}/api/projects/${projectId}/prompts/export?category=${category}`
    : `${getApiBase()}/api/projects/${projectId}/prompts/export`
  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to export prompts')
  return res.json()
}

export async function importPrompts(
  projectId: string,
  prompts: PromptUpdate[],
): Promise<{ imported: number; updated: number; failed: number }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/import`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts }),
    },
  )
  if (!res.ok) throw new Error('Failed to import prompts')
  return res.json()
}
